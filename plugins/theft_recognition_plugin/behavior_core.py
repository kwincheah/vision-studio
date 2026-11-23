"""Behavioral state machine, 2x3 visual sequence grid builder, and cross-camera pickup pool for Apex Vision."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import importlib.util
import os
import sys
import threading
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np


def _load_local(name: str):
    pkg = __package__ or ""
    full = f"{pkg}.{name}" if pkg else name
    if full in sys.modules:
        return sys.modules[full]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{name}.py")
    spec = importlib.util.spec_from_file_location(full, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(full, None)
        raise
    return mod


LocalizedShelfDeltaTracker = _load_local("shelf_delta").LocalizedShelfDeltaTracker


@dataclass
class PixelZone:
    name: str
    role: str = "shelf"
    x_norm: float = 0.0
    y_norm: float = 0.0
    w_norm: float = 0.0
    h_norm: float = 0.0
    pixel_rect: Optional[Tuple[int, int, int, int]] = None

    def to_pixel_rect(self, frame_w: int, frame_h: int) -> Optional[Tuple[int, int, int, int]]:
        if self.w_norm > 0.0 and self.h_norm > 0.0:
            x = max(0, min(frame_w - 1, int(round(self.x_norm * frame_w))))
            y = max(0, min(frame_h - 1, int(round(self.y_norm * frame_h))))
            w = max(1, min(frame_w - x, int(round(self.w_norm * frame_w))))
            h = max(1, min(frame_h - y, int(round(self.h_norm * frame_h))))
            return (x, y, w, h)
        if self.pixel_rect is not None:
            rx, ry, rw, rh = self.pixel_rect
            if rw > 0 and rh > 0:
                x = max(0, min(frame_w - 1, int(rx)))
                y = max(0, min(frame_h - 1, int(ry)))
                w = max(1, min(frame_w - x, int(rw)))
                h = max(1, min(frame_h - y, int(rh)))
                return (x, y, w, h)
        return None


def coerce_zones(zones: Optional[Sequence[Any]]) -> List[PixelZone]:
    out: List[PixelZone] = []
    for idx, z in enumerate(zones or ()):
        if isinstance(z, PixelZone):
            out.append(z)
        elif isinstance(z, dict):
            name = str(z.get("name") or f"zone_{idx + 1}")
            role = str(z.get("role") or "shelf").strip().lower()
            if role not in ("shelf", "aisle"):
                role = "aisle" if "aisle" in name.lower() else "shelf"
            rn = z.get("rect_norm")
            if isinstance(rn, (list, tuple)) and len(rn) == 4:
                out.append(PixelZone(name=name, role=role, x_norm=float(rn[0]), y_norm=float(rn[1]), w_norm=float(rn[2]), h_norm=float(rn[3])))
            else:
                rect = z.get("rect")
                if isinstance(rect, (list, tuple)) and len(rect) == 4:
                    rx, ry, rw, rh = [int(v) for v in rect]
                    out.append(PixelZone(name=name, role=role, pixel_rect=(rx, ry, rw, rh)))
        elif hasattr(z, "to_pixel_rect"):
            rn = getattr(z, "rect_norm", None)
            if isinstance(rn, (list, tuple)) and len(rn) == 4:
                zx, zy, zw, zh = float(rn[0]), float(rn[1]), float(rn[2]), float(rn[3])
            else:
                zx = float(getattr(z, "x_norm", 0.0) or 0.0)
                zy = float(getattr(z, "y_norm", 0.0) or 0.0)
                zw = float(getattr(z, "w_norm", 0.0) or 0.0)
                zh = float(getattr(z, "h_norm", 0.0) or 0.0)
            out.append(
                PixelZone(
                    name=str(getattr(z, "name", f"zone_{idx + 1}")),
                    role=str(getattr(z, "role", "shelf")),
                    x_norm=zx,
                    y_norm=zy,
                    w_norm=zw,
                    h_norm=zh,
                )
            )
    return out


def _decode_jpg(raw: bytes) -> Optional[np.ndarray]:
    if not raw:
        return None
    return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)


def _ensure_bgr_u8(img: np.ndarray) -> np.ndarray:
    """Normalize arbitrary grayscale/BGRA/multi-channel/non-uint8 arrays to uint8 3-channel BGR."""
    if img.dtype == np.uint8 and img.ndim == 3 and img.shape[2] == 3:
        return img
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3:
        c = img.shape[2]
        if c == 1:
            return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
        if c == 2:
            return np.dstack([img[:, :, 0], img[:, :, 1], img[:, :, 0]])
        if c == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        if c > 3:
            return np.ascontiguousarray(img[:, :, :3])
    return img


def _encode_jpg_crop(
    frame_bgr: np.ndarray,
    crop_rect: Optional[Tuple[int, int, int, int]] = None,
    max_dim: int = 640,
    quality: int = 85,
) -> bytes:
    if frame_bgr is None or frame_bgr.size == 0:
        return b""
    work = _ensure_bgr_u8(frame_bgr)
    h, w = work.shape[:2]
    if crop_rect is not None:
        cx, cy, cw, ch = [int(v) for v in crop_rect]
        if cw >= 32 and ch >= 32:
            x1 = max(0, min(w - 1, cx))
            y1 = max(0, min(h - 1, cy))
            x2 = max(x1 + 1, min(w, cx + cw))
            y2 = max(y1 + 1, min(h, cy + ch))
            if (x2 - x1) >= 32 and (y2 - y1) >= 32:
                work = work[y1:y2, x1:x2]
    ah, aw = work.shape[:2]
    if max(ah, aw) > max_dim:
        s = max_dim / float(max(ah, aw))
        work = cv2.resize(work, (max(1, int(aw * s)), max(1, int(ah * s))))
    ok, buf = cv2.imencode(".jpg", work, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else b""


def _fit_tile(arr: np.ndarray, size: int, title: str, color: Tuple[int, int, int]) -> np.ndarray:
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    if arr is None or arr.size == 0:
        return canvas
    ah, aw = arr.shape[:2]
    top = 24
    scale = min(size / float(max(1, aw)), (size - top) / float(max(1, ah)))
    nw, nh = max(1, int(aw * scale)), max(1, int(ah * scale))
    rsz = cv2.resize(arr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x0 = (size - nw) // 2
    y0 = top + ((size - top) - nh) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = rsz
    cv2.putText(canvas, title, (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return canvas


def build_2x3_grid(track_state: Dict[str, Any], fallback_overview_bgr: np.ndarray, tile_px: int = 384) -> np.ndarray:
    """Assemble 1 overview tile + 5 chronological phase tiles into a 2x3 grid."""
    samples = list(track_state.get("samples") or [])
    if not samples:
        return fallback_overview_bgr.copy() if fallback_overview_bgr is not None else np.zeros((tile_px * 2, tile_px * 3, 3), dtype=np.uint8)

    def nearest(target: float | None, lo: int, hi: int, phases: Tuple[str, ...] = ()) -> int:
        cands = [i for i in range(lo, hi + 1) if samples[i][2] in phases] if phases else []
        if cands:
            return cands[0] if target is None else min(cands, key=lambda i: abs(samples[i][0] - target))
        return (lo + hi) // 2 if target is None else min(range(lo, hi + 1), key=lambda i: abs(samples[i][0] - target))

    n = len(samples)
    mid_ts = (
        track_state.get("last_conceal_ts")
        or track_state.get("tuck_ts")
        or track_state.get("bladed_ts")
        or track_state.get("crouch_ts")
        or track_state.get("armed_ts")
    )
    i_mid = nearest(mid_ts, 0, n - 1, ("TUCK", "BLADED", "CROUCH"))
    i_reach = nearest(track_state.get("reach_peak_ts") or track_state.get("reach_ts"), 0, i_mid, ("REACH",))
    i_pre = nearest(samples[i_reach][0] - 1.8, 0, i_reach, ("PRE", "BROWSE"))
    post_ts = samples[i_mid][0] + 1.5 if i_mid < n - 1 else None
    i_post = nearest(post_ts, min(n - 1, i_mid), n - 1, ("POST",))

    idxs = sorted({i_pre, i_reach, i_mid, i_post, n - 1})
    for idx in np.linspace(0, n - 1, 5, dtype=int).tolist():
        if len(idxs) >= 5:
            break
        if idx not in idxs:
            idxs.append(idx)
    idxs.sort()
    while len(idxs) < 5:
        idxs.append(idxs[-1])

    ov = _decode_jpg(track_state.get("peak_ov", b""))
    if ov is None:
        ov = fallback_overview_bgr

    tiles = [_fit_tile(ov, tile_px, f"1. AISLE OVERVIEW | ID:{track_state['id']}", (0, 220, 255))]
    t0 = samples[idxs[0]][0]
    for k, si in enumerate(idxs[:5], start=2):
        ts, jpg, phase = samples[si]
        crop = _decode_jpg(jpg)
        if crop is None:
            crop = ov
        color = (0, 140, 255) if phase in ("REACH", "TUCK", "BLADED", "CROUCH") else (120, 235, 160)
        tiles.append(_fit_tile(crop, tile_px, f"{k}. t+{max(0.0, ts - t0):.1f}s [{phase}]", color))

    return np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:6])])


def extract_sequence_frames(track_state: Dict[str, Any], max_frames: int = 14) -> List[bytes]:
    """Select up to `max_frames` chronological JPEG crops prioritizing dense action transitions."""
    samples = list(track_state.get("samples") or [])
    if not samples:
        pre = track_state.get("pre_reach_jpg")
        return [pre] if pre else []
    limit = max(2, int(max_frames))
    pre_jpg = track_state.get("pre_reach_jpg") or b""

    if len(samples) <= limit:
        seq = [jpg for _, jpg, _ in samples if jpg]
    else:
        chosen: set[int] = {0, len(samples) - 1}
        mid_ts = (
            track_state.get("tuck_ts")
            or track_state.get("bladed_ts")
            or track_state.get("crouch_ts")
            or track_state.get("armed_ts")
        )
        reach_ts = track_state.get("reach_peak_ts") or track_state.get("reach_ts")
        last_conceal_ts = track_state.get("last_conceal_ts")

        # Prioritize dense consecutive samples around [reach - 0.5 .. last_conceal + 2.0] so
        # critical hand-to-bag/pocket transitions aren't lost in sparse uniform sampling.
        win_idxs: List[int] = []
        anchors = [float(t) for t in (reach_ts, mid_ts, last_conceal_ts) if t is not None]
        if anchors:
            win_lo = min(anchors) - 0.5
            win_hi = max(anchors) + 2.0
            win_idxs = [
                i
                for i, (ts, _, ph) in enumerate(samples)
                if (win_lo <= ts <= win_hi) or ph in ("REACH", "TUCK", "BLADED", "CROUCH", "POST", "RELEASE")
            ]
        else:
            win_idxs = [
                i
                for i, (_, _, ph) in enumerate(samples)
                if ph in ("REACH", "TUCK", "BLADED", "CROUCH", "POST", "RELEASE")
            ]

        action_budget = max(0, limit - len(chosen))
        if win_idxs and action_budget > 0:
            if len(win_idxs) <= action_budget:
                chosen.update(win_idxs)
            else:
                for pos in np.linspace(0, len(win_idxs) - 1, action_budget, dtype=int).tolist():
                    chosen.add(int(win_idxs[int(pos)]))

        if len(chosen) < limit:
            for idx in np.linspace(0, len(samples) - 1, limit, dtype=int).tolist():
                if len(chosen) >= limit:
                    break
                chosen.add(int(idx))

        seq = [samples[i][1] for i in sorted(chosen)[:limit] if samples[i][1]]

    if pre_jpg and seq and pre_jpg != seq[0]:
        if len(seq) < limit:
            seq = [pre_jpg] + seq
        elif len(seq) > 2:
            seq = [pre_jpg] + seq[1:]
        else:
            seq = [pre_jpg, seq[-1]]
    return seq[:limit]


def augment_sequence_with_ring_context(
    sequence_frames: List[bytes],
    ring_frames: List[Tuple[float, bytes]],
    *,
    first_sample_ts: Optional[float] = None,
    clean_scene_jpg: bytes = b"",
    crop_rect: Optional[Tuple[int, int, int, int]] = None,
    max_frames: int = 14,
) -> List[bytes]:
    """Prepend earlier chronological pre-reach/entry context frames from the rolling ring buffer."""
    seq = [f for f in (sequence_frames or []) if f]
    limit = max(2, int(max_frames))

    prepended: List[bytes] = []
    if ring_frames:
        if first_sample_ts is not None:
            earlier = [(ts, jpg) for ts, jpg in ring_frames if jpg and float(ts) < (float(first_sample_ts) - 0.5)]
        else:
            earlier = []

        if not earlier and len(seq) < limit:
            span_n = max(1, len(ring_frames) // 2)
            earlier = [(ts, jpg) for ts, jpg in ring_frames[:span_n] if jpg]

        if earlier:
            # Take up to 2..4 earliest/approach context frames spaced chronologically
            target_extra = min(4, max(2, limit - len(seq)))
            idxs = (
                list(range(len(earlier)))
                if len(earlier) <= target_extra
                else np.linspace(0, len(earlier) - 1, target_extra, dtype=int).tolist()
            )
            seen_pos = set()
            for idx in idxs:
                if idx in seen_pos:
                    continue
                seen_pos.add(idx)
                _, raw_jpg = earlier[idx]
                if crop_rect is not None:
                    decoded = _decode_jpg(raw_jpg)
                    enc = _encode_jpg_crop(decoded, crop_rect=crop_rect) if decoded is not None else raw_jpg
                    prepended.append(enc or raw_jpg)
                else:
                    prepended.append(raw_jpg)

    if not prepended and clean_scene_jpg and len(seq) < limit and (not seq or clean_scene_jpg != seq[0]):
        if crop_rect is not None:
            decoded = _decode_jpg(clean_scene_jpg)
            enc = _encode_jpg_crop(decoded, crop_rect=crop_rect) if decoded is not None else clean_scene_jpg
            prepended.append(enc or clean_scene_jpg)
        else:
            prepended.append(clean_scene_jpg)

    if not prepended:
        if len(seq) <= limit:
            return seq
        pick_idxs = sorted({int(i) for i in np.linspace(0, len(seq) - 1, limit, dtype=int).tolist()})
        return [seq[i] for i in pick_idxs]

    combined = prepended + seq
    if len(combined) <= limit:
        return combined

    # Preserve prepended early baseline frames + final departure frame + evenly thinned middle frames
    keep_head = min(len(prepended), 3)
    tail_count = limit - keep_head
    rest = combined[keep_head:]
    if len(rest) <= tail_count:
        return combined[:keep_head] + rest
    pick_idxs = sorted({int(i) for i in np.linspace(0, len(rest) - 1, tail_count, dtype=int).tolist()})
    return combined[:keep_head] + [rest[i] for i in pick_idxs]

def compute_upper_color_hist(crop_bgr: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """Compute a normalized upper-torso HSV histogram for rush-hour tie-breaking.

    Returns ``None`` if the crop is missing or too small to isolate the torso.
    Never used as a hard identity filter — only as a soft ranking tie-breaker
    when more than ``max_tiles`` pickups are active simultaneously.
    """
    if crop_bgr is None or not isinstance(crop_bgr, np.ndarray) or crop_bgr.size == 0:
        return None
    if crop_bgr.ndim < 3 or crop_bgr.shape[2] < 3:
        return None
    h, w = crop_bgr.shape[:2]
    if h < 12 or w < 12:
        return None

    y1 = max(0, int(round(h * 0.12)))
    y2 = min(h, max(y1 + 4, int(round(h * 0.55))))
    x1 = max(0, int(round(w * 0.15)))
    x2 = min(w, max(x1 + 4, int(round(w * 0.85))))
    torso = crop_bgr[y1:y2, x1:x2]
    if torso.size == 0:
        return None

    hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).astype(np.float32).flatten()
    norm = float(np.linalg.norm(hist))
    if norm <= 1e-6:
        return None
    return hist / norm


def _hist_similarity(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    """Cosine similarity in [0.0, 1.0] between two normalized color histograms."""
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        return 0.0
    sim = float(np.dot(a, b))
    return max(0.0, min(1.0, sim))


def _encode_crop_jpeg(crop_bgr: np.ndarray, max_dim: int = 288, quality: int = 80) -> Optional[bytes]:
    if crop_bgr is None or crop_bgr.size == 0:
        return None
    crop_bgr = _ensure_bgr_u8(crop_bgr)
    h, w = crop_bgr.shape[:2]
    if h <= 0 or w <= 0:
        return None
    scale = min(1.0, float(max_dim) / float(max(h, w)))
    resized = (
        cv2.resize(crop_bgr, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else crop_bgr
    )
    ok, buf = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return bytes(buf) if ok else None


@dataclass
class PickupEntry:
    camera_id: str
    track_id: int
    ts: float
    crop_jpeg: bytes
    shelf_zone: str = ""
    delta_score: float = 0.0
    upper_color_hist: Optional[np.ndarray] = None
    resolution: str = "pending"
    extra: Dict[str, Any] = field(default_factory=dict)


class RecentPickupsPool:
    """Thread-safe rolling store of recent shelf pickups across all cameras."""

    def __init__(self, ttl_sec: float = 120.0, max_entries: int = 24) -> None:
        self.ttl_sec = max(5.0, float(ttl_sec))
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()
        self._entries: List[PickupEntry] = []

    def prune(self, now_ts: float) -> None:
        with self._lock:
            self._prune_unlocked(float(now_ts))

    def _prune_unlocked(self, now_ts: float) -> None:
        self._entries = [
            e for e in self._entries
            if 0.0 <= (now_ts - e.ts) <= self.ttl_sec or (now_ts < e.ts and (e.ts - now_ts) <= 2.0)
        ]
        # Keep only up to max_entries newest
        if len(self._entries) > self.max_entries:
            self._entries.sort(key=lambda e: e.ts, reverse=True)
            self._entries = self._entries[: self.max_entries]

    def record_pickup(
        self,
        *,
        camera_id: str,
        track_id: int,
        ts: float,
        person_crop_bgr: Optional[np.ndarray] = None,
        crop_jpeg: Optional[bytes] = None,
        shelf_zone: str = "",
        delta_score: float = 0.0,
        upper_color_hist: Optional[np.ndarray] = None,
        resolution: str = "pending",
        dedup_sec: float = 6.0,
    ) -> Optional[PickupEntry]:
        now = float(ts)
        jpeg_bytes = crop_jpeg if crop_jpeg else (
            _encode_crop_jpeg(person_crop_bgr) if person_crop_bgr is not None else None
        )
        if not jpeg_bytes:
            return None

        hist = upper_color_hist if upper_color_hist is not None else compute_upper_color_hist(person_crop_bgr)
        entry = PickupEntry(
            camera_id=str(camera_id),
            track_id=int(track_id),
            ts=now,
            crop_jpeg=jpeg_bytes,
            shelf_zone=str(shelf_zone or "shelf"),
            delta_score=float(delta_score),
            upper_color_hist=hist,
            resolution=str(resolution or "pending"),
        )

        with self._lock:
            self._prune_unlocked(now)
            # Deduplicate rapid updates for the exact same (camera_id, track_id)
            replaced = False
            for idx, existing in enumerate(self._entries):
                if (
                    existing.camera_id == entry.camera_id
                    and existing.track_id == entry.track_id
                    and abs(now - existing.ts) <= dedup_sec
                ):
                    if existing.resolution == "carried_openly" and entry.resolution == "pending":
                        entry.resolution = "carried_openly"
                    if entry.upper_color_hist is None:
                        entry.upper_color_hist = existing.upper_color_hist
                    self._entries[idx] = entry
                    replaced = True
                    break
            if not replaced:
                self._entries.append(entry)
            if len(self._entries) > self.max_entries:
                self._entries.sort(key=lambda e: e.ts, reverse=True)
                self._entries = self._entries[: self.max_entries]
        return entry

    def mark_resolution(
        self,
        camera_id: str,
        track_id: int,
        resolution: str,
        now_ts: Optional[float] = None,
    ) -> bool:
        """Update resolution of matching recent pickup (`carried_openly`, `returned`, `concealed`)."""
        cam_s = str(camera_id)
        tid = int(track_id)
        res = str(resolution or "").strip().lower()
        updated = False
        with self._lock:
            if now_ts is not None:
                self._prune_unlocked(float(now_ts))
            for idx in range(len(self._entries) - 1, -1, -1):
                if self._entries[idx].camera_id == cam_s and self._entries[idx].track_id == tid:
                    if res == "returned":
                        self._entries.pop(idx)
                    else:
                        self._entries[idx].resolution = res
                    updated = True
                    break
        return updated

    def get_active(
        self,
        now_ts: float,
        exclude_camera_track: Optional[Tuple[str, int]] = None,
    ) -> List[PickupEntry]:
        now = float(now_ts)
        with self._lock:
            self._prune_unlocked(now)
            items = [
                e for e in self._entries
                if e.resolution != "returned"
                and (exclude_camera_track is None or (e.camera_id, e.track_id) != exclude_camera_track)
            ]
            items.sort(key=lambda e: e.ts, reverse=True)
            return list(items)

    def build_reference_sheet(
        self,
        now_ts: float,
        query_hist: Optional[np.ndarray] = None,
        max_tiles: int = 6,
        tile_px: int = 240,
        exclude_camera_track: Optional[Tuple[str, int]] = None,
    ) -> Tuple[Optional[bytes], List[Dict[str, Any]]]:
        """Build a 1x2 / 2x2 / 2x3 JPEG contact sheet of recent store pickups.

        Returns ``(sheet_jpeg_bytes, selected_metadata_list)`` or ``(None, [])``
        when no active pickups exist inside the 2-minute window.
        """
        now = float(now_ts)
        cap = max(1, min(6, int(max_tiles)))
        candidates = self.get_active(now, exclude_camera_track=exclude_camera_track)
        if not candidates:
            return None, []

        scored: List[Tuple[float, PickupEntry, float]] = []
        if len(candidates) <= cap:
            for e in candidates:
                sim = _hist_similarity(query_hist, e.upper_color_hist)
                scored.append((e.ts, e, sim))
            scored.sort(key=lambda item: item[0], reverse=True)
        else:
            # Rush-hour soft tie-breaker: recency + upper-torso color similarity
            for e in candidates:
                age = max(0.0, now - e.ts)
                recency = max(0.0, 1.0 - (age / self.ttl_sec))
                sim = _hist_similarity(query_hist, e.upper_color_hist)
                rank = 0.60 * recency + 0.40 * sim
                scored.append((rank, e, sim))
            scored.sort(key=lambda item: (item[0], item[1].ts), reverse=True)

        selected = scored[:cap]
        n = len(selected)
        cols = 2 if n <= 4 else 3
        rows = 1 if n <= 2 else 2

        banner_h = 28
        label_h = 22
        t_w = max(160, int(tile_px))
        t_h = max(160, int(tile_px))
        canvas = np.full((banner_h + rows * t_h, cols * t_w, 3), (20, 24, 32), dtype=np.uint8)

        # Header banner
        cv2.rectangle(canvas, (0, 0), (cols * t_w, banner_h), (29, 36, 48), -1)
        cv2.line(canvas, (0, banner_h - 1), (cols * t_w, banner_h - 1), (56, 72, 96), 1)
        cv2.putText(
            canvas,
            f"RECENT STORE PICKUPS (LAST {int(self.ttl_sec)}s) - REF SHEET",
            (10, 19),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (240, 244, 248),
            1,
            cv2.LINE_AA,
        )

        meta: List[Dict[str, Any]] = []
        for idx, (_score, entry, sim) in enumerate(selected):
            r = idx // cols
            c = idx % cols
            x0 = c * t_w
            y0 = banner_h + r * t_h

            arr = np.frombuffer(entry.crop_jpeg, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            inner_h = t_h - label_h - 4
            inner_w = t_w - 4
            if img is not None and img.size > 0:
                ih, iw = img.shape[:2]
                scale = min(float(inner_w) / float(max(1, iw)), float(inner_h) / float(max(1, ih)))
                nw = max(1, int(round(iw * scale)))
                nh = max(1, int(round(ih * scale)))
                resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
                px = x0 + 2 + (inner_w - nw) // 2
                py = y0 + label_h + 2 + (inner_h - nh) // 2
                canvas[py : py + nh, px : px + nw] = resized

            # Top label bar per tile
            is_open = entry.resolution == "carried_openly"
            strip_bg = (22, 85, 58) if is_open else (34, 42, 56)
            cv2.rectangle(canvas, (x0, y0), (x0 + t_w - 1, y0 + label_h), strip_bg, -1)

            age_s = max(0, int(round(now - entry.ts)))
            zone_short = (entry.shelf_zone or "shelf")[:14]
            tag = " OPEN" if is_open else ""
            label_text = f"#{idx + 1} {entry.camera_id} | {age_s}s ago | {zone_short}{tag}"
            cv2.putText(
                canvas,
                label_text[:40],
                (x0 + 6, y0 + 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (245, 248, 252),
                1,
                cv2.LINE_AA,
            )
            cv2.rectangle(canvas, (x0, y0), (x0 + t_w - 1, y0 + t_h - 1), (56, 68, 88), 1)

            meta.append({
                "tile": idx + 1,
                "camera_id": entry.camera_id,
                "track_id": entry.track_id,
                "age_sec": round(max(0.0, now - entry.ts), 2),
                "shelf_zone": entry.shelf_zone,
                "delta_score": round(entry.delta_score, 3),
                "resolution": entry.resolution,
                "color_sim": round(sim, 3),
            })

        ok, out_buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return None, []
        return bytes(out_buf), meta

PixelRect = Tuple[int, int, int, int]

_PERSONAL_BAG_CLASSES = {"backpack", "handbag", "suitcase", "tote bag", "tote", "purse", "bag"}
_BENIGN_VESSEL_CLASSES = {"shopping basket", "shopping cart", "basket", "cart"}
_PHONE_CLASSES = {"cell phone", "smartphone", "phone"}


def _pt_in_any(px: float, py: float, rects: Sequence[PixelRect], pad: int = 0) -> bool:
    for rx, ry, rw, rh in rects:
        if (rx - pad) <= px <= (rx + rw + pad) and (ry - pad) <= py <= (ry + rh + pad):
            return True
    return False


def _in_aisle(bbox: Tuple[int, int, int, int], aisle_rects: Sequence[PixelRect]) -> bool:
    if not aisle_rects:
        return True
    x, y, bw, bh = bbox
    cx = x + bw * 0.5
    return _pt_in_any(cx, y + bh * 0.55, aisle_rects) or _pt_in_any(cx, y + bh * 0.92, aisle_rects)


def _derive_hr_rects(aisle_rects: List[PixelRect], shelf_rects: List[PixelRect], w: int, h: int) -> List[PixelRect]:
    if aisle_rects:
        return aisle_rects
    derived: List[PixelRect] = []
    for sx, sy, sw, sh in shelf_rects:
        px, py = max(80, int(sw * 0.85)), max(60, int(sh * 0.45))
        x1, y1 = max(0, sx - px), max(0, sy - py // 2)
        x2, y2 = min(w, sx + sw + px), min(h, sy + sh + py)
        derived.append((x1, y1, max(1, x2 - x1), max(1, y2 - y1)))
    return derived


def _boxes_close(b1: Tuple[int, int, int, int], b2: Tuple[int, int, int, int], m: int = 36) -> bool:
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2
    return not (x1 + w1 + m < x2 or x2 + w2 + m < x1 or y1 + h1 + m < y2 or y2 + h2 + m < y1)


def _encode_jpg(arr: np.ndarray, max_dim: int = 640, quality: int = 85) -> bytes:
    if arr is None or arr.size == 0:
        return b""
    arr = _ensure_bgr_u8(arr)
    ah, aw = arr.shape[:2]
    if max(ah, aw) > max_dim:
        s = max_dim / float(max(ah, aw))
        arr = cv2.resize(arr, (max(1, int(aw * s)), max(1, int(ah * s))))
    ok, buf = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else b""


def _crop_person(frame_bgr: np.ndarray, x: int, y: int, bw: int, bh: int, w_img: int, h_img: int) -> Optional[np.ndarray]:
    if frame_bgr is None or frame_bgr.size == 0 or bw <= 0 or bh <= 0:
        return None
    pad_x = max(16, int(round(bw * 0.14)))
    pad_y = max(12, int(round(bh * 0.08)))
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(w_img, x + bw + pad_x)
    y2 = min(h_img, y + bh + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame_bgr[y1:y2, x1:x2]
    return crop.copy() if crop.size > 0 else None


def _pose_cues(
    kps: List[Any],
    p_bbox: PixelRect,
    shelf_rects: List[PixelRect],
    bag_boxes: List[PixelRect],
    basket_boxes: List[PixelRect],
    phone_boxes: List[PixelRect],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "reach_side": "",
        "touched_shelf_idx": None,
        "wrist_pts": [],
        "tucked": False,
        "occluded": False,
        "in_core_or_bag": False,
        "in_core": False,
        "tight_core": False,
        "in_personal_bag": False,
        "wrist_open": False,
        "two_hands_torso": False,
        "in_benign_basket": False,
        "holding_phone": False,
        "norm_sh": None,
    }
    if not isinstance(kps, list) or len(kps) < 13:
        return out

    def pt(idx: int) -> Optional[Tuple[float, float]]:
        p = kps[idx]
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return None
        conf = float(p[2]) if len(p) > 2 else 0.9
        x, y = float(p[0]), float(p[1])
        if conf < 0.30 or (x <= 0 and y <= 0):
            return None
        return (x, y)

    ls, rs = pt(5), pt(6)
    le, re = pt(7), pt(8)
    lw, rw = pt(9), pt(10)
    lh, rh = pt(11), pt(12)
    nose = pt(0)
    px, py, pw, ph = p_bbox

    torso_h = max(24.0, ph * 0.42)
    if (ls or rs) and (lh or rh):
        sy = float(np.mean([p[1] for p in (ls, rs) if p is not None]))
        hy = float(np.mean([p[1] for p in (lh, rh) if p is not None]))
        torso_h = max(20.0, abs(hy - sy))
    if ls and rs:
        out["norm_sh"] = abs(ls[0] - rs[0]) / torso_h

    sh_cx = float(np.mean([p[0] for p in (ls, rs) if p is not None])) if (ls or rs) else (px + pw * 0.5)
    sh_cy = float(np.mean([p[1] for p in (ls, rs) if p is not None])) if (ls or rs) else (py + ph * 0.28)
    waist_y = float(np.mean([p[1] for p in (lh, rh) if p is not None])) if (lh or rh) else (py + ph * 0.55)

    reach_sides: List[str] = []
    for side, wp in (("left", lw), ("right", rw)):
        if wp is None:
            continue
        out["wrist_pts"].append((int(round(wp[0])), int(round(wp[1]))))
        stretch = ((wp[0] - sh_cx) ** 2 + (wp[1] - sh_cy) ** 2) ** 0.5
        if shelf_rects:
            for s_idx, s_rect in enumerate(shelf_rects):
                rx, ry, rw_s, rh_s = s_rect
                if rx <= wp[0] <= rx + rw_s and ry <= wp[1] <= ry + rh_s:
                    reach_sides.append(side)
                    if out["touched_shelf_idx"] is None:
                        out["touched_shelf_idx"] = s_idx
                    break
        elif (
            not _pt_in_any(wp[0], wp[1], bag_boxes)
            and not _pt_in_any(wp[0], wp[1], basket_boxes)
            and wp[1] <= sh_cy + 0.55 * torso_h
            and stretch > max(0.90 * torso_h, 0.50 * pw)
            and abs(wp[0] - sh_cx) > max(0.85 * pw, 0.90 * torso_h)
        ):
            reach_sides.append(side)

    if reach_sides:
        out["reach_side"] = "+".join(reach_sides)

    torso_arms = 0
    for side, wp in (("left", lw), ("right", rw)):
        if wp is None:
            continue
        in_basket = _pt_in_any(wp[0], wp[1], basket_boxes, pad=10)
        on_phone = _pt_in_any(wp[0], wp[1], phone_boxes, pad=14)
        in_bag = _pt_in_any(wp[0], wp[1], bag_boxes)
        in_core = abs(wp[0] - sh_cx) <= max(28.0, 0.36 * pw) and (sh_cy - 10.0) <= wp[1] <= (waist_y + 0.25 * torso_h)
        tight_core = abs(wp[0] - sh_cx) <= max(12.0, 0.22 * pw) and (sh_cy - 10.0) <= wp[1] <= (waist_y + 0.25 * torso_h)

        if in_core or in_bag:
            torso_arms += 1
        elif not in_basket and not on_phone:
            out["wrist_open"] = True

        if side in reach_sides:
            out["wrist_open"] = True
            continue

        if in_basket and not in_bag:
            out["in_benign_basket"] = True
            continue
        if on_phone and not in_bag:
            out["holding_phone"] = True
        if in_bag:
            out["in_personal_bag"] = True
        if in_core and not on_phone:
            out["in_core"] = True
        if tight_core and not on_phone:
            out["tight_core"] = True
        if in_core or in_bag:
            out["in_core_or_bag"] = True
            out["tucked"] = True

    if torso_arms >= 2 or (torso_arms >= 1 and len(out["wrist_pts"]) < 2):
        out["two_hands_torso"] = True

    if shelf_rects or nose is not None:
        for ep, wp in ((le, lw), (re, rw)):
            if ep is not None and wp is None:
                if _pt_in_any(ep[0], ep[1], basket_boxes, pad=14) and not _pt_in_any(ep[0], ep[1], bag_boxes):
                    out["in_benign_basket"] = True
                    continue
                if abs(ep[0] - sh_cx) <= max(35.0, 0.45 * pw) and (sh_cy - 10.0) <= ep[1] <= (waist_y + 0.35 * torso_h):
                    out["occluded"] = True
                    break
    return out


class BehaviorGate:
    """Isolated per-camera behavioral state machine + rolling crop buffer."""

    BUFFER_SEC = 12.0
    SAMPLE_SEC = 0.35
    ACTION_SAMPLE_SEC = 0.25
    TUCK_WIN_SEC = 7.0
    MERCH_TTL_SEC = 60.0
    BAG_RECENT_TTL_SEC = 3.0
    CARRY_ESCALATION_HOLD_SEC = 0.40
    BASKET_LATCH_FRAMES = 3
    BAG_STUFF_HOLD_SEC = 0.50
    GARMENT_HOLD_SEC = 0.70
    CROUCH_HOLD_SEC = 0.60
    BLADE_DROP = 0.40
    CROUCH_DROP = 0.28
    ID_LOSS_GRACE_SEC = 0.8
    MIN_FRAMES = 4
    TILE_PX = 384

    def __init__(
        self,
        camera_id: str,
        camera_name: str,
        *,
        dwell_sec: float = 3.0,
        release_wait_sec: float = 3.5,
        cooldown_sec: float = 12.0,
        zones: Sequence[Any] = (),
    ):
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.dwell_sec = float(dwell_sec)
        self.release_wait_sec = float(release_wait_sec)
        self.cooldown_sec = float(cooldown_sec)

        self._lock = threading.Lock()
        self._zones: List[Any] = coerce_zones(zones)
        self._tracks: Dict[int, Dict[str, Any]] = {}
        self._dispatch_queue: Deque[Tuple[np.ndarray, Dict[str, Any]]] = deque(maxlen=16)
        self._pickup_events: Deque[Dict[str, Any]] = deque(maxlen=32)
        self._prev_raw_ts: Optional[float] = None
        self._ts_offset: float = 0.0
        self._shelf_delta = LocalizedShelfDeltaTracker()
        self._clean_scene_jpg: bytes = b""
        self._clean_scene_ts: float = -1e9

    def pop_pickup_events(self) -> List[Dict[str, Any]]:
        """Drain recent shelf-pickup crop events captured by this camera."""
        with self._lock:
            items = list(self._pickup_events)
            self._pickup_events.clear()
            return items

    def mark_carried_openly(self, track_id: int, ttl_sec: float = 60.0) -> None:
        """Keep Path A open-carry merchandise memory active when VLM reports carried_openly."""
        with self._lock:
            st = self._tracks.get(int(track_id))
            if st is None:
                return
            now_ref = float(st["last_seen"])
            until = now_ref + max(5.0, float(ttl_sec))
            st["has_merchandise_until"] = max(float(st.get("has_merchandise_until") or 0.0), until)
            st["carried_openly_confirmed_until"] = until
            st["carry_escalation_ready"] = True
            st["carry_escalation_since"] = None
            st["carry_escalation_not_before"] = float(st.get("last_dispatch_ts") or now_ref) + 2.0

    def update_zones(self, zones: Sequence[Any]) -> None:
        new_zones = coerce_zones(zones)
        sig_new = [(z.name, z.role, round(z.x_norm, 6), round(z.y_norm, 6), round(z.w_norm, 6), round(z.h_norm, 6), z.pixel_rect) for z in new_zones]
        with self._lock:
            sig_old = [(z.name, z.role, round(z.x_norm, 6), round(z.y_norm, 6), round(z.w_norm, 6), round(z.h_norm, 6), z.pixel_rect) for z in self._zones]
            zones_changed = sig_new != sig_old
            self._zones = new_zones
            if zones_changed:
                self._shelf_delta.reset()

    def update_timing(self, *, camera_name: str, dwell_sec: float, release_wait_sec: float, cooldown_sec: float, zones: Sequence[Any]) -> None:
        new_zones = coerce_zones(zones)
        sig_new = [(z.name, z.role, round(z.x_norm, 6), round(z.y_norm, 6), round(z.w_norm, 6), round(z.h_norm, 6), z.pixel_rect) for z in new_zones]
        with self._lock:
            sig_old = [(z.name, z.role, round(z.x_norm, 6), round(z.y_norm, 6), round(z.w_norm, 6), round(z.h_norm, 6), z.pixel_rect) for z in self._zones]
            zones_changed = sig_new != sig_old
            self.camera_name = camera_name
            self.dwell_sec = float(dwell_sec)
            self.release_wait_sec = float(release_wait_sec)
            self.cooldown_sec = float(cooldown_sec)
            self._zones = new_zones
            if zones_changed:
                self._shelf_delta.reset()

    def has_armed_tracks(self) -> bool:
        with self._lock:
            return any(st.get("armed_ts") is not None for st in self._tracks.values()) or len(self._dispatch_queue) > 0

    def get_track_states(self) -> Dict[int, Dict[str, Any]]:
        """Return lightweight status snapshot per active track for live camera overlays."""
        with self._lock:
            return {
                int(tid): {
                    "phase": str(st.get("last_phase") or ""),
                    "armed": st.get("armed_ts") is not None,
                    "dwell": round(float(st.get("dwell") or 0.0), 1),
                    "in_zone": bool(st.get("in_zone")),
                }
                for tid, st in self._tracks.items()
            }

    def flush_armed_on_clip_end(self, frame_bgr: Optional[np.ndarray]) -> List[Tuple[np.ndarray, Dict[str, Any]]]:
        """Drain queued candidates and finalize any still-armed tracks at local clip EOF, then reset gate."""
        with self._lock:
            out: List[Tuple[np.ndarray, Dict[str, Any]]] = list(self._dispatch_queue)
            self._dispatch_queue.clear()
            if frame_bgr is not None and frame_bgr.size > 0:
                zone_names = [z.name for z in self._zones]
                for st in list(self._tracks.values()):
                    if (
                        st.get("armed_ts") is not None
                        and not self._should_suppress_active_browse(st)
                        and float(st.get("last_seen", 0.0)) >= float(st.get("cooldown", 0.0))
                    ):
                        out.append(self._build_candidate(st, frame_bgr, "clip_end", zone_names))
            self._tracks.clear()
            self._shelf_delta.reset()
            self._clean_scene_jpg = b""
            self._clean_scene_ts = -1e9
            return out

    def reset_all(self) -> None:
        """Completely clear all tracks, buffers, timestamps, and shelf baselines."""
        with self._lock:
            self._tracks.clear()
            self._dispatch_queue.clear()
            self._pickup_events.clear()
            self._prev_raw_ts = None
            self._ts_offset = 0.0
            self._shelf_delta.reset()
            self._clean_scene_jpg = b""
            self._clean_scene_ts = -1e9

    def on_video_loop_restart(self) -> None:
        """Reset loop cooldowns and shelf baselines when a local video file rewinds to frame 0."""
        with self._lock:
            self._shelf_delta.reset()
            self._clean_scene_jpg = b""
            self._clean_scene_ts = -1e9
            for tid, st in list(self._tracks.items()):
                if st.get("armed_ts") is not None:
                    st["cooldown"] = 0.0
                    st["carried_openly_confirmed_until"] = None
                    st["has_merchandise_until"] = None
                    st["carry_escalation_ready"] = False
                    st["carry_escalation_since"] = None
                    st["carry_escalation_not_before"] = 0.0
                    st["bag_seen_ts"].clear()
                    st["bags"].clear()
                    st["episode_bags"].clear()
                else:
                    self._tracks.pop(tid, None)

    def _monotonic_ts(self, raw_ts: float) -> float:
        cur = float(raw_ts)
        if self._prev_raw_ts is not None and cur + 0.05 < self._prev_raw_ts:
            self._ts_offset += self._prev_raw_ts + (1.0 / 24.0)
        self._prev_raw_ts = cur
        return self._ts_offset + cur

    def _build_candidate(
        self,
        st: Dict[str, Any],
        frame_bgr: np.ndarray,
        cause: str,
        zone_names: List[str],
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        if st["samples"]:
            ts_l, jpg_l, _ = st["samples"][-1]
            st["samples"][-1] = (ts_l, jpg_l, "RELEASE")
        grid = build_2x3_grid(st, frame_bgr, self.TILE_PX)
        seq_frames = extract_sequence_frames(st, max_frames=14)
        samples = st.get("samples") or []
        first_ts = st.get("first_sample_raw_ts")
        if first_ts is None and samples:
            first_ts = max(0.0, float(samples[0][0]) - self._ts_offset)
        tid = int(st["id"])
        delta_status = str(st.get("shelf_delta_status") or "none")
        delta_score = float(st.get("shelf_delta_score") or 0.0)
        delta_confirmed = bool(st.get("shelf_delta_confirmed"))
        trigger_mode = str(st.get("trigger_mode") or "shelf_reach_and_delta")
        cand = {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "track_id": tid,
            "bbox": list(st["bbox"]),
            "dwell_sec": round(st["dwell"], 2),
            "reach_side": st["reach_side"],
            "behaviors": list(st["reasons"]),
            "nearby_bags": sorted(st["bags"] | set(st.get("episode_bags") or ())),
            "context_vessels": sorted(st.get("vessels") or ()),
            "has_store_vessel": bool(st.get("has_store_vessel")),
            "zone_names": zone_names or ["full_frame"],
            "dispatch_cause": cause,
            "trigger_mode": trigger_mode,
            "shelf_delta_status": delta_status,
            "shelf_delta_score": delta_score,
            "shelf_delta_confirmed": delta_confirmed,
            "sequence_frames": seq_frames,
            "first_sample_ts": first_ts,
            "pre_reach_jpg": st.get("pre_reach_jpg") or b"",
            "clean_scene_jpg": self._clean_scene_jpg or b"",
            "union_crop_rect": st.get("union_crop_rect"),
            "upper_color_hist": st.get("upper_color_hist"),
            "reason_hint": (
                f"Track ID #{tid} mode={trigger_mode} dwell={st['dwell']:.1f}s cause={cause} "
                f"shelf_delta={delta_status}({delta_score:.2f}) "
                f"vessels={','.join(sorted(st.get('vessels') or ())) or 'none'}"
            ),
        }
        return grid, cand

    @staticmethod
    def _should_suppress_active_browse(st: Dict[str, Any]) -> bool:
        return (
            st.get("trigger_mode") == "shelf_reach_and_delta"
            and not st["shelf_delta_confirmed"]
            and not st.get("armed_bag_contact")
            and int(st.get("post_arm_reach_frames") or 0) >= 2
        )

    @staticmethod
    def _reset_armed_cycle(st: Dict[str, Any]) -> None:
        st["armed_ts"] = st["reach_ts"] = st["reach_peak_ts"] = st["tuck_ts"] = st["bladed_ts"] = st["crouch_ts"] = None
        st["last_conceal_ts"] = None
        st["bag_stuff_since"] = st["garment_hide_since"] = st["crouch_hide_since"] = None
        st["trigger_mode"] = "shelf_reach_and_delta"
        st["pickup_delta_logged"] = False
        st["post_arm_reach_frames"] = 0
        st["armed_bag_contact"] = False
        st["reasons"].clear()
        st["episode_bags"].clear()
        st["shelf_delta_status"] = "none"
        st["shelf_delta_score"] = 0.0
        st["shelf_delta_confirmed"] = False

    def step(
        self,
        frame_bgr: np.ndarray,
        raw_ts: float,
        tracks: List[Dict[str, Any]],
        bag_dets: List[Dict[str, Any]],
    ) -> Tuple[Optional[np.ndarray], Optional[Dict[str, Any]], Dict[str, Any]]:
        if frame_bgr is None or frame_bgr.size == 0:
            return None, None, {"tracks": 0, "gate_state": "NO_IMAGE"}

        with self._lock:
            h_img, w_img = frame_bgr.shape[:2]
            now = self._monotonic_ts(raw_ts)

            shelf_rects: List[PixelRect] = []
            shelf_zone_names: List[str] = []
            aisle_rects: List[PixelRect] = []
            zone_names: List[str] = []
            for z in self._zones:
                rect = z.to_pixel_rect(w_img, h_img)
                if rect is None:
                    continue
                zone_names.append(z.name)
                if z.role == "shelf":
                    shelf_rects.append(rect)
                    shelf_zone_names.append(z.name)
                else:
                    aisle_rects.append(rect)
            hr_rects = _derive_hr_rects(aisle_rects, shelf_rects, w_img, h_img)

            bags = [b for b in (bag_dets or []) if isinstance(b, dict) and isinstance(b.get("Box") or b.get("bbox"), (list, tuple))]
            bag_boxes: List[PixelRect] = [tuple(int(round(float(v))) for v in (b.get("Box") or b.get("bbox"))[:4]) for b in bags]
            bag_labels: List[str] = [str(b.get("Class", b.get("label", "bag"))).strip().lower() for b in bags]

            # Pass 1: associate vessels and compute pose cues for all active tracks
            prepared: List[Tuple[int, Dict[str, Any], PixelRect, Dict[str, Any], List[PixelRect], bool]] = []
            delta_inputs: List[Dict[str, Any]] = []
            seen = set()

            for tr in tracks or []:
                if not isinstance(tr, dict):
                    continue
                tid = int(tr.get("track_id", -1))
                bb = tr.get("bbox") or []
                if tid < 0 or len(bb) < 4:
                    continue
                x, y, bw, bh = [int(v) for v in bb[:4]]
                seen.add(tid)
                st = self._tracks.setdefault(
                    tid,
                    {
                        "id": tid, "last_seen": now, "fc": 0, "in_zone": False, "enter_ts": None, "exit_ts": None,
                        "dwell": 0.0, "samples": deque(maxlen=80), "last_samp": -1e9, "sh": deque(maxlen=40),
                        "zone_sh": deque(maxlen=40), "heights": deque(maxlen=40), "last_y2": None,
                        "reach_ts": None, "reach_peak_ts": None, "reach_side": "", "tuck_ts": None,
                        "bladed_ts": None, "crouch_ts": None, "armed_ts": None, "reasons": [], "peak_ov": b"",
                        "last_conceal_ts": None, "last_dispatch_ts": None, "last_phase": "",
                        "cooldown": 0.0, "bags": set(), "bag_seen_ts": {}, "episode_bags": set(),
                        "vessels": set(), "bbox": [x, y, bw, bh],
                        "last_touched_shelf_idx": None, "shelf_delta_status": "none",
                        "shelf_delta_score": 0.0, "shelf_delta_confirmed": False,
                        "basket_hits": 0, "basket_miss": 0, "has_store_vessel": False,
                        "wrist_was_open": False, "bag_stuff_since": None,
                        "garment_hide_since": None, "crouch_hide_since": None,
                        "last_center": None, "norm_speed": 0.0,
                        "has_merchandise_until": None, "carried_openly_confirmed_until": None,
                        "carry_escalation_ready": False, "carry_escalation_since": None, "carry_escalation_not_before": 0.0,
                        "last_pickup_recorded_ts": -1e9, "pickup_delta_logged": False,
                        "trigger_mode": "shelf_reach_and_delta", "upper_color_hist": None,
                        "pre_reach_jpg": b"", "pre_reach_ts": None, "post_arm_reach_frames": 0,
                        "armed_bag_contact": False,
                        "first_sample_ts": None, "union_crop_rect": None,
                    },
                )
                cx_t, cy_t = x + bw * 0.5, y + bh * 0.5
                prev_c = st.get("last_center")
                if prev_c is not None and (now - prev_c[0]) > 1e-4:
                    dt_c = now - prev_c[0]
                    dist_c = ((cx_t - prev_c[1]) ** 2 + (cy_t - prev_c[2]) ** 2) ** 0.5
                    st["norm_speed"] = (dist_c / dt_c) / max(40.0, float(bh))
                else:
                    st["norm_speed"] = 0.0
                st["last_center"] = (now, cx_t, cy_t)
                st["last_seen"] = now
                st["fc"] += 1
                st["bbox"] = [x, y, bw, bh]

                margin = max(30, int(bw * 0.25))
                near_bags: List[PixelRect] = []
                near_baskets: List[PixelRect] = []
                near_phones: List[PixelRect] = []
                near_all_vessels: List[PixelRect] = []
                for idx_b, bb_i in enumerate(bag_boxes):
                    if not _boxes_close((x, y, bw, bh), bb_i, margin):
                        continue
                    lbl = bag_labels[idx_b]
                    st["vessels"].add(lbl)
                    if lbl in _BENIGN_VESSEL_CLASSES:
                        near_baskets.append(bb_i)
                        near_all_vessels.append(bb_i)
                    elif lbl in _PHONE_CLASSES:
                        near_phones.append(bb_i)
                    elif lbl in _PERSONAL_BAG_CLASSES or "bag" in lbl:
                        near_bags.append(bb_i)
                        near_all_vessels.append(bb_i)
                        st["bag_seen_ts"][lbl] = now

                stale_bags = [lbl_b for lbl_b, ts_b in st["bag_seen_ts"].items() if (now - float(ts_b)) > self.BAG_RECENT_TTL_SEC]
                for lbl_b in stale_bags:
                    st["bag_seen_ts"].pop(lbl_b, None)
                st["bags"] = set(st["bag_seen_ts"].keys())
                if st["reach_ts"] is not None or st["armed_ts"] is not None:
                    st["episode_bags"].update(st["bags"])

                if near_baskets:
                    st["basket_hits"] = min(12, int(st["basket_hits"]) + 1)
                    st["basket_miss"] = 0
                    if st["basket_hits"] >= self.BASKET_LATCH_FRAMES:
                        st["has_store_vessel"] = True
                else:
                    st["basket_miss"] = int(st["basket_miss"]) + 1
                    if st["basket_miss"] >= 15:
                        st["has_store_vessel"] = False
                        st["basket_hits"] = 0

                in_hr = _in_aisle((x, y, bw, bh), hr_rects)
                cues = _pose_cues(tr.get("keypoints") or [], (x, y, bw, bh), shelf_rects, near_bags, near_baskets, near_phones)
                if cues["wrist_open"]:
                    st["wrist_was_open"] = True
                if cues["touched_shelf_idx"] is not None:
                    st["last_touched_shelf_idx"] = cues["touched_shelf_idx"]

                prepared.append((tid, st, (x, y, bw, bh), cues, near_all_vessels, in_hr))
                delta_inputs.append({
                    "tid": tid,
                    "bbox": (x, y, bw, bh),
                    "wrists": cues["wrist_pts"],
                    "reach_active": bool(cues["reach_side"]),
                    "touched_shelf_idx": cues["touched_shelf_idx"],
                })

            if not self._clean_scene_jpg or (len(prepared) == 0 and (now - self._clean_scene_ts) >= 5.0):
                clean_enc = _encode_jpg(frame_bgr)
                if clean_enc:
                    self._clean_scene_jpg = clean_enc
                    self._clean_scene_ts = now

            delta_map = self._shelf_delta.step(frame_bgr, now, shelf_rects, delta_inputs)

            # Pass 2: update track state machines, multi-shelf crops, and dispatch queue
            for tid, st, (x, y, bw, bh), cues, near_all_vessels, in_hr in prepared:
                d_res = delta_map.get(tid) or {}
                d_status = str(d_res.get("status") or "none")
                d_score = float(d_res.get("score") or 0.0)
                d_conf = bool(d_res.get("confirmed"))

                if d_conf:
                    st["shelf_delta_status"] = "confirmed"
                    st["shelf_delta_score"] = max(float(st.get("shelf_delta_score") or 0.0), d_score)
                    st["shelf_delta_confirmed"] = True
                elif not st.get("shelf_delta_confirmed") and d_status != "none":
                    st["shelf_delta_status"] = d_status
                    st["shelf_delta_score"] = d_score

                if in_hr:
                    st["in_zone"] = True
                    st["exit_ts"] = None
                    if st["enter_ts"] is None:
                        st["enter_ts"] = now
                    st["dwell"] = now - st["enter_ts"]
                else:
                    if st["exit_ts"] is None:
                        st["exit_ts"] = now
                    if (now - st["exit_ts"]) > 0.5:
                        if st["armed_ts"] is not None and now >= st["cooldown"]:
                            self._dispatch_queue.append(self._build_candidate(st, frame_bgr, "zone_exit", zone_names))
                            st["last_dispatch_ts"] = now
                            st["cooldown"] = now + self.cooldown_sec
                        st["in_zone"] = False
                        st["enter_ts"] = None
                        st["dwell"] = 0.0
                        st["zone_sh"].clear()
                        self._reset_armed_cycle(st)
                        self._shelf_delta.clear_episode(tid)

                mature = st["in_zone"] and st["dwell"] >= self.dwell_sec and st["fc"] >= self.MIN_FRAMES
                fast_shelf_ready = (
                    st["in_zone"]
                    and st["dwell"] >= min(self.dwell_sec, 0.5)
                    and st["fc"] >= 3
                    and bool(st["shelf_delta_confirmed"])
                    and not cues["in_benign_basket"]
                )
                reach_now = bool(cues["reach_side"])
                pre_reach_path_b = (
                    st["armed_ts"] is not None
                    and st.get("trigger_mode") == "shelf_free_tuck"
                    and st["reach_ts"] is None
                    and "bag_stuff" not in st["reasons"]
                    and "crouch_hide" not in st["reasons"]
                )
                if pre_reach_path_b and (reach_now or d_conf):
                    self._reset_armed_cycle(st)
                if reach_now or d_conf:
                    if reach_now and st["armed_ts"] is None:
                        if st["reach_ts"] is None:
                            st["reach_ts"] = now
                        st["reach_peak_ts"] = now
                        st["reach_side"] = cues["reach_side"]
                    st["has_merchandise_until"] = max(float(st.get("has_merchandise_until") or 0.0), now + self.MERCH_TTL_SEC)
                    need_pickup_log = (now - float(st["last_pickup_recorded_ts"])) >= 4.0 or (
                        d_conf and not st.get("pickup_delta_logged")
                    )
                    if need_pickup_log:
                        p_crop = _crop_person(frame_bgr, x, y, bw, bh, w_img, h_img)
                        if p_crop is not None:
                            lsi = st.get("last_touched_shelf_idx")
                            z_lbl = (
                                shelf_zone_names[int(lsi)]
                                if lsi is not None and 0 <= int(lsi) < len(shelf_zone_names)
                                else (shelf_zone_names[0] if shelf_zone_names else (zone_names[0] if zone_names else "aisle"))
                            )
                            self._pickup_events.append({
                                "camera_id": self.camera_id,
                                "track_id": tid,
                                "ts": float(raw_ts),
                                "person_crop_bgr": p_crop,
                                "shelf_zone": z_lbl,
                                "delta_score": float(st.get("shelf_delta_score") or d_score),
                                "upper_color_hist": compute_upper_color_hist(p_crop),
                            })
                            st["last_pickup_recorded_ts"] = now
                            if d_conf:
                                st["pickup_delta_logged"] = True

                raw_tucked = cues["tucked"] or cues["occluded"]
                phone_suppress = cues["holding_phone"] and not st["shelf_delta_confirmed"]
                effective_tuck = raw_tucked and not cues["in_benign_basket"] and not phone_suppress
                conc = bool(effective_tuck or len(cues["wrist_pts"]) < 2)

                pool = st["zone_sh"] if len(st["zone_sh"]) >= 4 else st["sh"]
                bladed_frame = (
                    (not reach_now or conc)
                    and conc
                    and not cues["in_benign_basket"]
                    and cues["norm_sh"] is not None
                    and len(pool) >= 3
                    and cues["norm_sh"] <= float(np.percentile(list(pool), 85)) * (1.0 - self.BLADE_DROP)
                )
                crouch_frame = False
                if (not reach_now or conc) and not cues["in_benign_basket"] and len(st["heights"]) >= 3:
                    bh_base = float(np.percentile(list(st["heights"]), 90))
                    y2 = y + bh
                    steady = st["last_y2"] is None or abs(y2 - st["last_y2"]) <= max(28.0, bh_base * 0.12)
                    crouch_frame = bh_base > 30.0 and bh <= bh_base * (1.0 - self.CROUCH_DROP) and steady

                tuck_now = bladed_now = crouch_now = False
                bag_stuff_hit = garment_hit = crouch_hide_hit = False
                has_merchandise_active = st["has_merchandise_until"] is not None and now <= float(st["has_merchandise_until"])
                cd_ok = now >= st["cooldown"]
                if (
                    not cd_ok
                    and st.get("carry_escalation_ready")
                    and has_merchandise_active
                    and st["armed_ts"] is None
                    and now >= float(st.get("carry_escalation_not_before") or 0.0)
                ):
                    strong_carry_cue = (
                        not reach_now
                        and not cues["in_benign_basket"]
                        and not phone_suppress
                        and (
                            cues["in_personal_bag"]
                            or (cues["occluded"] and bladed_frame)
                            or (crouch_frame and (cues["in_core"] or cues["in_personal_bag"] or cues["occluded"]))
                        )
                    )
                    if strong_carry_cue:
                        if st["carry_escalation_since"] is None:
                            st["carry_escalation_since"] = now
                        elif (now - float(st["carry_escalation_since"])) >= self.CARRY_ESCALATION_HOLD_SEC:
                            st["cooldown"] = now
                            cd_ok = True
                            st["carry_escalation_ready"] = False
                            st["carry_escalation_since"] = None
                    else:
                        st["carry_escalation_since"] = None
                elif st["armed_ts"] is not None or not has_merchandise_active:
                    st["carry_escalation_since"] = None
                fast_reach_tuck = (
                    st["in_zone"]
                    and st["dwell"] >= min(self.dwell_sec, 1.0)
                    and st["fc"] >= self.MIN_FRAMES
                    and st["reach_ts"] is not None
                    and not cues["in_benign_basket"]
                    and not phone_suppress
                    and (cues["in_personal_bag"] or (cues["in_core"] and cues["two_hands_torso"]))
                )

                if (mature or fast_shelf_ready or fast_reach_tuck) and st["armed_ts"] is None:
                    if reach_now:
                        if st["reach_ts"] is None:
                            st["reach_ts"] = now
                        st["reach_peak_ts"] = now
                        st["reach_side"] = cues["reach_side"]
                    dt_r = (now - st["reach_ts"]) if st["reach_ts"] is not None else -1.0
                    rec_r = st["reach_ts"] is not None and 0.15 <= dt_r <= self.TUCK_WIN_SEC

                    if rec_r and effective_tuck:
                        tuck_now = True
                        st["tuck_ts"] = now
                    if rec_r and bladed_frame and (effective_tuck or st["shelf_delta_confirmed"] or cues["in_personal_bag"]):
                        bladed_now = True
                        st["bladed_ts"] = now
                    if rec_r and crouch_frame:
                        crouch_now = True
                        st["crouch_ts"] = now

                    # Path A delayed open-carry fallback within 60s of pickup/reach
                    if has_merchandise_active and not rec_r and not reach_now:
                        if effective_tuck or bladed_frame or crouch_frame:
                            if effective_tuck:
                                tuck_now = True
                                st["tuck_ts"] = now
                            if bladed_frame and (effective_tuck or cues["occluded"]):
                                bladed_now = True
                                st["bladed_ts"] = now
                            if crouch_frame:
                                crouch_now = True
                                st["crouch_ts"] = now
                            st["trigger_mode"] = "carry_delayed"

                if not bladed_frame and not bladed_now and cues["norm_sh"] is not None:
                    st["sh"].append(float(cues["norm_sh"]))
                    if in_hr and not reach_now:
                        st["zone_sh"].append(float(cues["norm_sh"]))
                if not crouch_frame and not crouch_now:
                    st["heights"].append(float(bh))
                st["last_y2"] = float(y + bh)

                # Path B: Smart Shelf-Free Tuck (catches cross-cam concealment with zero ReID)
                mature_b = st["in_zone"] and st["dwell"] >= min(self.dwell_sec, 0.8) and st["fc"] >= self.MIN_FRAMES
                vessel_suppress = st["has_store_vessel"] and not cues["in_personal_bag"]
                path_b_eligible = (
                    mature_b
                    and cd_ok
                    and st["armed_ts"] is None
                    and st["reach_ts"] is None
                    and not reach_now
                    and not st["shelf_delta_confirmed"]
                    and not has_merchandise_active
                    and st["wrist_was_open"]
                    and not cues["in_benign_basket"]
                    and not vessel_suppress
                    and not phone_suppress
                )
                if path_b_eligible:
                    bag_cond = cues["in_personal_bag"] and not cues["holding_phone"]
                    slowed_down = float(st.get("norm_speed") or 0.0) <= 0.85
                    garment_cond = (
                        (cues["in_core"] or (cues["occluded"] and bladed_frame))
                        and slowed_down
                        and (cues["two_hands_torso"] or bladed_frame)
                        and not cues["holding_phone"]
                    )
                    crouch_cond = (
                        crouch_frame
                        and (cues["in_core"] or cues["in_personal_bag"] or cues["occluded"])
                        and not cues["holding_phone"]
                    )

                    if bag_cond:
                        if st["bag_stuff_since"] is None:
                            st["bag_stuff_since"] = now
                        elif (now - st["bag_stuff_since"]) >= self.BAG_STUFF_HOLD_SEC:
                            bag_stuff_hit = True
                    else:
                        st["bag_stuff_since"] = None

                    if garment_cond:
                        if st["garment_hide_since"] is None:
                            st["garment_hide_since"] = now
                        elif (now - st["garment_hide_since"]) >= self.GARMENT_HOLD_SEC:
                            garment_hit = True
                    else:
                        st["garment_hide_since"] = None

                    if crouch_cond:
                        if st["crouch_hide_since"] is None:
                            st["crouch_hide_since"] = now
                        elif (now - st["crouch_hide_since"]) >= self.CROUCH_HOLD_SEC:
                            crouch_hide_hit = True
                    else:
                        st["crouch_hide_since"] = None
                else:
                    st["bag_stuff_since"] = st["garment_hide_since"] = st["crouch_hide_since"] = None

                path_b_hit = bag_stuff_hit or garment_hit or crouch_hide_hit

                phase = (
                    "TUCK" if (tuck_now or bag_stuff_hit or garment_hit) else
                    "BLADED" if bladed_now else
                    "CROUCH" if (crouch_now or crouch_hide_hit) else
                    "PRE" if not (mature or fast_shelf_ready or mature_b) else
                    "REACH" if reach_now else
                    "POST" if st["armed_ts"] is not None else
                    "BROWSE"
                )
                def _append_sample(phase_lbl: str) -> None:
                    ux1, uy1, ux2, uy2 = x, y, x + bw, y + bh
                    for bx, by, bbw, bbh in near_all_vessels:
                        ux1, uy1, ux2, uy2 = min(ux1, bx), min(uy1, by), max(ux2, bx + bbw), max(uy2, by + bbh)

                    target_shelf: Optional[PixelRect] = None
                    lsi = st.get("last_touched_shelf_idx")
                    if lsi is not None and 0 <= int(lsi) < len(shelf_rects):
                        target_shelf = shelf_rects[int(lsi)]
                    elif shelf_rects:
                        pcx = x + bw * 0.5
                        target_shelf = min(shelf_rects, key=lambda r: abs((r[0] + r[2] * 0.5) - pcx))

                    if target_shelf is not None:
                        sx_t, sy_t, sw_t, sh_t = target_shelf
                        if bh < 0.35 * float(h_img):
                            reach_r = max(120, int(bh * 1.5))
                            sx1 = max(sx_t, x - reach_r)
                            sy1 = max(sy_t, y - reach_r // 2)
                            sx2 = min(sx_t + sw_t, x + bw + reach_r)
                            sy2 = min(sy_t + sh_t, y + bh + reach_r // 2)
                            if sx2 > sx1 and sy2 > sy1:
                                ux1 = min(ux1, sx1)
                                uy1 = min(uy1, sy1)
                                ux2 = max(ux2, sx2)
                                uy2 = max(uy2, sy2)
                        elif (sw_t * sh_t) <= 0.45 * float(w_img * h_img):
                            ux1 = min(ux1, sx_t)
                            uy1 = min(uy1, sy_t)
                            ux2 = max(ux2, sx_t + sw_t)
                            uy2 = max(uy2, sy_t + sh_t)
                        else:
                            ux1 = min(ux1, sx_t + sw_t // 3)
                            ux2 = max(ux2, sx_t + (2 * sw_t) // 3)
                            uy2 = max(uy2, sy_t + sh_t)

                    pad_x, pad_y = max(35, int((ux2 - ux1) * 0.25)), max(25, int((uy2 - uy1) * 0.12))
                    cx1, cy1 = max(0, ux1 - pad_x), max(0, uy1 - pad_y)
                    cx2, cy2 = min(w_img, ux2 + pad_x), min(h_img, uy2 + pad_y)
                    prev_u = st.get("union_crop_rect")
                    if prev_u is None:
                        st["union_crop_rect"] = (cx1, cy1, max(1, cx2 - cx1), max(1, cy2 - cy1))
                    else:
                        ux_p, uy_p, uw_p, uh_p = prev_u
                        nx1 = min(ux_p, cx1)
                        ny1 = min(uy_p, cy1)
                        nx2 = max(ux_p + uw_p, cx2)
                        ny2 = max(uy_p + uh_p, cy2)
                        st["union_crop_rect"] = (nx1, ny1, max(1, nx2 - nx1), max(1, ny2 - ny1))

                    jpg = _encode_jpg(frame_bgr[cy1:cy2, cx1:cx2])
                    if jpg:
                        st["samples"].append((now, jpg, phase_lbl))
                        st["last_samp"] = now
                        if st["first_sample_ts"] is None:
                            st["first_sample_ts"] = now
                            st["first_sample_raw_ts"] = float(raw_ts)
                        if phase_lbl != "RELEASE" and (st["reach_ts"] is None or not st["pre_reach_jpg"]):
                            st["pre_reach_jpg"] = jpg
                            st["pre_reach_ts"] = now

                is_action_phase = phase in ("REACH", "TUCK", "BLADED", "CROUCH")
                phase_changed = is_action_phase and phase != st.get("last_phase")
                sample_interval = self.ACTION_SAMPLE_SEC if is_action_phase else self.SAMPLE_SEC
                if st["in_zone"] and (phase_changed or (now - st["last_samp"]) >= sample_interval or not st["samples"]):
                    _append_sample(phase)
                if st["in_zone"]:
                    st["last_phase"] = phase
                while st["samples"] and (now - st["samples"][0][0]) > self.BUFFER_SEC:
                    st["samples"].popleft()

                fast_delta_hit = fast_shelf_ready and (tuck_now or bladed_now or crouch_now or cues["in_core_or_bag"] or not reach_now)
                path_a_hit = (
                    cd_ok
                    and (((mature or fast_reach_tuck) and (tuck_now or bladed_now or crouch_now)) or fast_delta_hit)
                    and not cues["in_benign_basket"]
                )
                hit = path_a_hit or (path_b_hit and not cues["in_benign_basket"])

                if path_b_hit and not path_a_hit and st["armed_ts"] is None:
                    st["trigger_mode"] = "shelf_free_tuck"
                elif path_a_hit and st["armed_ts"] is None and st.get("trigger_mode") != "carry_delayed":
                    st["trigger_mode"] = "shelf_reach_and_delta"

                if cd_ok and (hit or st["armed_ts"] is not None):
                    for flag, lbl in (
                        (tuck_now, "reach_and_tuck"),
                        (bladed_now, "blading"),
                        (crouch_now, "crouch"),
                        (fast_delta_hit, "shelf_item_removed"),
                        (st.get("trigger_mode") == "carry_delayed" and (tuck_now or bladed_now or crouch_now), "carry_delayed"),
                        (bag_stuff_hit, "bag_stuff"),
                        (garment_hit, "garment_hide"),
                        (crouch_hide_hit, "crouch_hide"),
                    ):
                        if flag and lbl not in st["reasons"]:
                            st["reasons"].append(lbl)
                conceal_active_now = (
                    not reach_now
                    and not cues["in_benign_basket"]
                    and not phone_suppress
                    and (
                        cues["in_personal_bag"]
                        or cues["occluded"]
                        or bladed_frame
                        or crouch_frame
                        or cues["tight_core"]
                    )
                )
                if hit and st["armed_ts"] is None:
                    st["armed_ts"] = now
                    st["last_conceal_ts"] = now
                    st["armed_bag_contact"] = bool(cues["in_personal_bag"])
                    st["episode_bags"].update(st["bags"])
                    p_crop = _crop_person(frame_bgr, x, y, bw, bh, w_img, h_img)
                    st["upper_color_hist"] = compute_upper_color_hist(p_crop)
                    ov = frame_bgr.copy()
                    cv2.rectangle(ov, (x, y), (x + bw, y + bh), (0, 60, 255), 3)
                    st["peak_ov"] = _encode_jpg(ov, max_dim=768)
                elif st["armed_ts"] is not None:
                    if cues["in_personal_bag"]:
                        st["armed_bag_contact"] = True
                    if reach_now and now > st["armed_ts"]:
                        st["post_arm_reach_frames"] = int(st.get("post_arm_reach_frames") or 0) + 1
                    if conceal_active_now:
                        st["last_conceal_ts"] = now

                if st["armed_ts"] is not None:
                    min_arm_sec = min(self.release_wait_sec, max(0.35, self.release_wait_sec * 0.65))
                    post_quiet_sec = min(1.75, max(0.25, self.release_wait_sec * 0.50))
                    max_arm_sec = min(self.BUFFER_SEC - 2.0, self.release_wait_sec + min(4.0, self.release_wait_sec * 1.15))
                    last_c = float(st["last_conceal_ts"] if st.get("last_conceal_ts") is not None else st["armed_ts"])
                    armed_elapsed = now - float(st["armed_ts"])
                    quiet_elapsed = now - last_c
                    ready_to_release = (
                        (armed_elapsed >= min_arm_sec and quiet_elapsed >= post_quiet_sec)
                        or armed_elapsed >= max_arm_sec
                    )
                    if ready_to_release:
                        if self._should_suppress_active_browse(st):
                            self._reset_armed_cycle(st)
                            self._shelf_delta.clear_episode(tid)
                            confirmed_until = st.get("carried_openly_confirmed_until")
                            if confirmed_until is None or float(confirmed_until) < now:
                                st["has_merchandise_until"] = None
                        else:
                            if st["in_zone"] and (now - st["last_samp"]) >= 0.15:
                                _append_sample("RELEASE")
                            self._dispatch_queue.append(self._build_candidate(st, frame_bgr, "natural_release", zone_names))
                            st["last_dispatch_ts"] = now
                            self._reset_armed_cycle(st)
                            self._shelf_delta.clear_episode(tid)
                            st["cooldown"] = now + self.cooldown_sec

                if st["armed_ts"] is None and st["reach_ts"] is not None and (now - st["reach_ts"]) > self.TUCK_WIN_SEC:
                    st["reach_ts"] = None

            for tid, st in list(self._tracks.items()):
                if tid in seen:
                    continue
                miss = now - st["last_seen"]
                if st["armed_ts"] is not None and miss >= self.ID_LOSS_GRACE_SEC and now >= st["cooldown"]:
                    if not self._should_suppress_active_browse(st):
                        self._dispatch_queue.append(self._build_candidate(st, frame_bgr, "id_disappearance", zone_names))
                    self._tracks.pop(tid, None)
                    self._shelf_delta.clear_episode(tid)
                elif miss > 15.0:
                    self._tracks.pop(tid, None)
                    self._shelf_delta.clear_track(tid)

            if self._dispatch_queue:
                grid_out, cand_out = self._dispatch_queue.popleft()
                return grid_out, cand_out, {"tracks": len(seen), "queued": len(self._dispatch_queue), "gate_state": "DISPATCH"}

            return None, None, {
                "tracks": len(seen),
                "queued": 0,
                "gate_state": "ARMED" if any(s["armed_ts"] is not None for s in self._tracks.values()) else "MONITORING",
            }
