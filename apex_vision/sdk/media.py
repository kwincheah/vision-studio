"""Media evidence helpers (2x3 grids, MP4 ring clips, disk retention, VLM JSONL audit logger) for Apex Vision SDK."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


def save_grid_jpeg(grid_bgr: np.ndarray, out_path: str | Path, quality: int = 88) -> str:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp" + p.suffix)
    ok, buf = cv2.imencode(".jpg", grid_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError(f"Failed to encode grid JPEG for {p}")
    with tmp.open("wb") as fh:
        fh.write(buf.tobytes())
    os.replace(tmp, p)
    return str(p)


def write_ring_clip_mp4(
    ring_frames: List[Tuple[float, bytes]],
    out_path: str | Path,
    default_fps: float = 8.0,
) -> Optional[str]:
    """Decode JPEG ring buffer frames into an MP4 file atomically."""
    if not ring_frames:
        return None
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    decoded: List[np.ndarray] = []
    for _, jpg in ring_frames:
        if not jpg:
            continue
        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None and frame.size > 0:
            decoded.append(frame)

    if not decoded:
        return None

    h, w = decoded[0].shape[:2]
    fps = max(1.0, min(30.0, float(default_fps)))
    if len(ring_frames) >= 2:
        dt = max(0.1, float(ring_frames[-1][0] - ring_frames[0][0]))
        est = (len(ring_frames) - 1) / dt
        if 1.0 <= est <= 30.0:
            fps = est

    tmp = p.with_name(p.stem + ".tmp" + p.suffix)
    writer = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        return None
    try:
        for frame in decoded:
            if frame.shape[0] != h or frame.shape[1] != w:
                frame = cv2.resize(frame, (w, h))
            writer.write(frame)
    finally:
        writer.release()

    if not tmp.is_file() or tmp.stat().st_size == 0:
        return None
    os.replace(tmp, p)
    return str(p)


def encode_ring_clip_mp4_bytes(
    ring_frames: List[Tuple[float, bytes]],
    default_fps: float = 8.0,
    max_dim: int = 640,
    max_bytes: int = 12 * 1024 * 1024,
) -> Optional[bytes]:
    """Encode ring-buffer JPEG frames into in-memory MP4 bytes for native video VLM APIs."""
    if not ring_frames or len(ring_frames) < 2:
        return None

    decoded: List[np.ndarray] = []
    valid_ts: List[float] = []
    for ts, jpg in ring_frames:
        if not jpg:
            continue
        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None and frame.size > 0:
            decoded.append(frame)
            valid_ts.append(float(ts))

    if len(decoded) < 2:
        return None

    fps = max(1.0, min(30.0, float(default_fps)))
    if len(valid_ts) >= 2:
        dt = max(0.1, float(valid_ts[-1] - valid_ts[0]))
        est = (len(valid_ts) - 1) / dt
        if 1.0 <= est <= 30.0:
            fps = est

    def _encode_at(dim_cap: int) -> Optional[bytes]:
        src_h, src_w = decoded[0].shape[:2]
        scale = min(1.0, float(dim_cap) / float(max(1, src_w, src_h)))
        out_w = max(16, int(round(src_w * scale)) & ~1)
        out_h = max(16, int(round(src_h * scale)) & ~1)

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
                tmp_path = tf.name
            writer = cv2.VideoWriter(tmp_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (out_w, out_h))
            if not writer.isOpened():
                return None
            try:
                for fr in decoded:
                    if fr.shape[1] != out_w or fr.shape[0] != out_h:
                        fr = cv2.resize(fr, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
                    writer.write(fr)
            finally:
                writer.release()
            data = Path(tmp_path).read_bytes()
            return data if len(data) > 0 else None
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except OSError:
                    pass

    data = _encode_at(max(240, int(max_dim)))
    if data and len(data) <= max_bytes:
        return data
    if max_dim > 480:
        data_small = _encode_at(480)
        if data_small and len(data_small) <= max_bytes:
            return data_small
    return None


class RetentionManager:
    """Periodic cleanup enforcing retention_days and max_evidence_gb limits."""

    def __init__(self, evidence_dir: str | Path, retention_days: int = 30, max_evidence_gb: float = 20.0):
        self.evidence_dir = Path(evidence_dir)
        self.retention_days = max(1, int(retention_days))
        self.max_evidence_gb = max(0.01, float(max_evidence_gb))
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def update_limits(self, retention_days: int, max_evidence_gb: float) -> None:
        with self._lock:
            self.retention_days = max(1, int(retention_days))
            self.max_evidence_gb = max(0.01, float(max_evidence_gb))

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run_loop, name="storeguard-retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        while not self._stop_evt.is_set():
            self.prune_now()
            self._stop_evt.wait(3600.0)

    def prune_now(self, *, now_epoch: Optional[float] = None) -> int:
        if not self.evidence_dir.is_dir():
            return 0
        with self._lock:
            cutoff = (now_epoch if now_epoch is not None else time.time()) - (self.retention_days * 86400.0)
            max_bytes = int(self.max_evidence_gb * (1024 ** 3))

            files: List[Tuple[float, int, Path]] = []
            for p in self.evidence_dir.rglob("*"):
                if p.is_file() and ".tmp" not in p.name:
                    st = p.stat()
                    files.append((st.st_mtime, st.st_size, p))

            files.sort(key=lambda item: item[0])  # oldest first
            removed = 0
            total_bytes = sum(sz for _, sz, _ in files)

            for mtime, sz, path in files:
                if mtime < cutoff or total_bytes > max_bytes:
                    try:
                        path.unlink()
                        total_bytes -= sz
                        removed += 1
                    except OSError:
                        pass
            return removed

logger = logging.getLogger("apex_vision.sdk.media")


class VlmAuditLogger:
    """Appends non-secret VLM request/verdict/error records to runtime_data/logs/vlm_calls.jsonl."""

    def __init__(self, logs_dir: str | Path):
        self.logs_dir = Path(logs_dir)
        self.jsonl_path = self.logs_dir / "vlm_calls.jsonl"
        self._lock = threading.Lock()

    def log_verdict(
        self,
        *,
        candidate: Dict[str, Any],
        provider: str,
        model_name: str,
        decision: str,
        conf_pct: float,
        threshold_pct: float,
        suppression_reasons: Optional[List[str]] = None,
        verdict: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        latency_sec: Optional[float] = None,
    ) -> None:
        rec = self._base_record(
            event="VLM_VERDICT",
            candidate=candidate,
            provider=provider,
            model_name=model_name,
            decision=decision,
            latency_sec=latency_sec,
        )
        rec.update(
            {
                "event_id": event_id,
                "confidence_pct": round(float(conf_pct), 2),
                "threshold_pct": round(float(threshold_pct), 2),
                "suppression_reasons": list(suppression_reasons or []),
                "verdict": dict(verdict or {}),
            }
        )
        self._append(rec)
        logger.info(
            "VLM %s cam=%s track=#%s mode=%s cat=%s conf=%.1f%% dest=%s latency=%s reasons=%s",
            decision,
            rec["camera_id"],
            rec["track_id"],
            rec["trigger_mode"],
            (verdict or {}).get("behavior_category", ""),
            conf_pct,
            (verdict or {}).get("visible_destination", ""),
            f"{latency_sec:.2f}s" if latency_sec is not None else "n/a",
            ",".join(rec["suppression_reasons"]) or "none",
        )

    def log_error(
        self,
        *,
        candidate: Dict[str, Any],
        provider: str,
        model_name: str,
        error_msg: str,
        grid_path: str = "",
        latency_sec: Optional[float] = None,
    ) -> None:
        rec = self._base_record(
            event="VLM_ERROR",
            candidate=candidate,
            provider=provider,
            model_name=model_name,
            decision="VLM_ERROR",
            latency_sec=latency_sec,
        )
        rec.update(
            {
                "error": str(error_msg or ""),
                "grid_path": str(grid_path or ""),
            }
        )
        self._append(rec)
        logger.warning(
            "VLM_ERROR cam=%s track=#%s provider=%s model=%s latency=%s err=%s",
            rec["camera_id"],
            rec["track_id"],
            provider,
            model_name,
            f"{latency_sec:.2f}s" if latency_sec is not None else "n/a",
            rec["error"],
        )

    @staticmethod
    def _base_record(
        *,
        event: str,
        candidate: Dict[str, Any],
        provider: str,
        model_name: str,
        decision: str,
        latency_sec: Optional[float],
    ) -> Dict[str, Any]:
        lat = latency_sec if latency_sec is not None else candidate.get("_vlm_latency_sec")
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "camera_id": str(candidate.get("camera_id", "cam")),
            "camera_name": str(candidate.get("camera_name", "")),
            "track_id": int(candidate.get("track_id", 0)),
            "trigger_mode": str(candidate.get("trigger_mode") or "shelf_reach_and_delta"),
            "behaviors": list(candidate.get("behaviors") or []),
            "shelf_delta_status": str(candidate.get("shelf_delta_status") or "none"),
            "shelf_delta_score": float(candidate.get("shelf_delta_score") or 0.0),
            "frame_count": len(candidate.get("sequence_frames") or []),
            "media_mode": str(candidate.get("_vlm_media_mode") or ""),
            "provider": str(provider or ""),
            "model_name": str(model_name or ""),
            "latency_sec": round(float(lat), 3) if lat is not None else None,
            "decision": decision,
        }

    def _append(self, rec: Dict[str, Any]) -> None:
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            try:
                self.logs_dir.mkdir(parents=True, exist_ok=True)
                with self.jsonl_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception:
                pass
