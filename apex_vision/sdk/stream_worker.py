"""Per-camera RTSP/video grabber worker with latest-frame slot and 10s JPEG ring buffer."""
from __future__ import annotations

from collections import deque
import os
import threading
import time
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

import logging
import re

ALL_OVERLAY_LAYERS: Tuple[str, ...] = ("aisle", "bags", "botsort", "motion", "pose", "shelf")

_SKELETON_EDGES: Tuple[Tuple[int, int], ...] = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
)

_FONT_LOCK = threading.Lock()
_FONT_CACHE: Dict[int, Any] = {}
_BADGE_CACHE: Dict[Tuple[str, int, Tuple[int, int, int], Tuple[int, int, int], Optional[Tuple[int, int, int]]], np.ndarray] = {}
_TTF_CANDIDATES: Tuple[str, ...] = (
    "C:/Windows/Fonts/seguisb.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _get_pil_font(font_px: int) -> Any:
    px = max(10, min(28, int(font_px)))
    with _FONT_LOCK:
        if px in _FONT_CACHE:
            return _FONT_CACHE[px]
        font_obj = None
        try:
            from PIL import ImageFont

            for path in _TTF_CANDIDATES:
                if os.path.isfile(path):
                    font_obj = ImageFont.truetype(path, px)
                    break
        except Exception:
            font_obj = None
        _FONT_CACHE[px] = font_obj
        return font_obj


def _render_badge_patch(
    text: str,
    font_px: int,
    pill_bgr: Tuple[int, int, int],
    txt_bgr: Tuple[int, int, int],
    border_bgr: Optional[Tuple[int, int, int]] = None,
) -> np.ndarray:
    label = str(text or "").strip() or "-"
    px = max(10, min(24, int(font_px)))
    b_col = tuple(int(c) for c in pill_bgr[:3])
    t_col = tuple(int(c) for c in txt_bgr[:3])
    brd_col = tuple(int(c) for c in border_bgr[:3]) if border_bgr is not None else None
    key = (label, px, b_col, t_col, brd_col)
    with _FONT_LOCK:
        cached = _BADGE_CACHE.get(key)
        if cached is not None:
            return cached

    font = _get_pil_font(px)
    patch: Optional[np.ndarray] = None
    if font is not None:
        try:
            from PIL import Image, ImageDraw

            dummy = Image.new("RGB", (4, 4))
            d0 = ImageDraw.Draw(dummy)
            bbox = d0.textbbox((0, 0), label, font=font)
            tw = max(1, int(bbox[2] - bbox[0]))
            th = max(1, int(bbox[3] - bbox[1]))
            pad_x = max(6, px // 2)
            pad_y = max(3, px // 4)
            pw = tw + pad_x * 2
            ph = th + pad_y * 2
            bg_rgb = (b_col[2], b_col[1], b_col[0])
            fg_rgb = (t_col[2], t_col[1], t_col[0])
            img = Image.new("RGB", (pw, ph), bg_rgb)
            draw = ImageDraw.Draw(img)
            if brd_col is not None:
                brd_rgb = (brd_col[2], brd_col[1], brd_col[0])
                draw.rectangle([0, 0, pw - 1, ph - 1], outline=brd_rgb, width=1)
            draw.text((pad_x - bbox[0], pad_y - bbox[1]), label, font=font, fill=fg_rgb)
            rgb_arr = np.asarray(img, dtype=np.uint8)
            patch = np.ascontiguousarray(rgb_arr[:, :, ::-1])
        except Exception:
            patch = None

    if patch is None:
        fscale = max(0.38, px / 26.0)
        fthick = 1
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, fscale, fthick)
        pad_x, pad_y = 6, 4
        pw = tw + pad_x * 2
        ph = th + baseline + pad_y * 2
        patch = np.empty((ph, pw, 3), dtype=np.uint8)
        patch[:] = b_col
        if brd_col is not None:
            cv2.rectangle(patch, (0, 0), (pw - 1, ph - 1), brd_col, 1)
        cv2.putText(
            patch,
            label,
            (pad_x, ph - baseline - pad_y),
            cv2.FONT_HERSHEY_DUPLEX,
            fscale,
            t_col,
            fthick,
            cv2.LINE_AA,
        )

    with _FONT_LOCK:
        if len(_BADGE_CACHE) >= 256:
            _BADGE_CACHE.pop(next(iter(_BADGE_CACHE)), None)
        _BADGE_CACHE[key] = patch
    return patch


def _draw_label_pill(
    frame: np.ndarray,
    text: str,
    x1: int,
    y1: int,
    pill_bgr: Tuple[int, int, int],
    txt_bgr: Tuple[int, int, int],
    *,
    font_px: int = 13,
    border_bgr: Optional[Tuple[int, int, int]] = None,
    above: bool = True,
) -> None:
    h, w = frame.shape[:2]
    if h < 12 or w < 20:
        return
    patch = _render_badge_patch(text, font_px, pill_bgr, txt_bgr, border_bgr)
    ph, pw = patch.shape[:2]
    if pw >= w or ph >= h:
        return
    px1 = max(0, min(w - pw, int(x1)))
    if above:
        if y1 >= ph + 2:
            py1 = y1 - ph - 2
        else:
            py1 = min(h - ph, max(0, y1 + 2))
    else:
        py1 = min(h - ph, max(0, y1))
    frame[py1 : py1 + ph, px1 : px1 + pw] = patch


def _parse_overlay_layers(overlays: bool, overlay_layers: Any) -> Tuple[str, ...]:
    if not overlays:
        return ()
    if overlay_layers is None:
        return ALL_OVERLAY_LAYERS
    if isinstance(overlay_layers, str):
        items = [s.strip().lower() for s in overlay_layers.split(",") if s.strip()]
    elif isinstance(overlay_layers, Iterable):
        items = [str(s).strip().lower() for s in overlay_layers if str(s).strip()]
    else:
        return ALL_OVERLAY_LAYERS
    return tuple(sorted(set(items)))

def mask_rtsp_url(url: str) -> str:
    return re.sub(r"://([^:@/]+):([^@/]+)@", r"://***:***@", str(url or ""))


def _clean_url(url: str) -> str:
    clean = str(url or "").strip().strip('"').strip("'")
    if clean.lower().startswith("file:///"):
        from urllib.parse import unquote
        clean = unquote(clean[8:])
    return clean


def _zone_to_rect(z: Any, w_img: int, h_img: int):
    if hasattr(z, "to_pixel_rect"):
        r = z.to_pixel_rect(w_img, h_img)
        return r, str(getattr(z, "role", "shelf") or "shelf"), str(getattr(z, "name", "zone") or "zone")
    if isinstance(z, dict):
        rn = z.get("rect_norm")
        role = str(z.get("role") or "shelf").lower()
        name = str(z.get("name") or "zone")
        if isinstance(rn, (list, tuple)) and len(rn) == 4:
            x = max(0, min(w_img - 1, int(round(float(rn[0]) * w_img))))
            y = max(0, min(h_img - 1, int(round(float(rn[1]) * h_img))))
            w = max(1, min(w_img - x, int(round(float(rn[2]) * w_img))))
            h = max(1, min(h_img - y, int(round(float(rn[3]) * h_img))))
            return (x, y, w, h), role, name
        rect = z.get("rect")
        if isinstance(rect, (list, tuple)) and len(rect) == 4:
            rx, ry, rw, rh = [int(v) for v in rect]
            if rw > 0 and rh > 0:
                return (rx, ry, rw, rh), role, name
    return None, "shelf", ""


def _open_rtsp_capture(url: str, decode_backend: str = "auto") -> Tuple[Any, str]:
    """Open live RTSP capture, probing PyAV HW decoders (NVDEC/QSV) before falling back to OpenCV CPU."""
    backend = str(decode_backend or "auto").strip().lower()
    if backend in ("auto", "hwaccel") and url.lower().startswith(("rtsp://", "rtsps://")):
        try:
            cap = _PyAvCapture(url, try_hwaccel=True)
            if cap.isOpened():
                return cap, cap.decoder_name
            cap.release()
        except Exception:
            pass
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
    cap = cv2.VideoCapture(url)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap, "opencv_cpu"


class _PyAvCapture:
    """Thin VideoCapture-compatible PyAV RTSP reader supporting CUVID/QSV hardware decoding and grab/retrieve split."""

    def __init__(self, url: str, *, try_hwaccel: bool = True):
        import av

        self._container = av.open(
            url,
            options={"rtsp_transport": "tcp", "stimeout": "5000000", "fflags": "nobuffer", "flags": "low_delay"},
            timeout=5.0,
        )
        v_stream = next((s for s in self._container.streams if s.type == "video"), None)
        if v_stream is None:
            self._container.close()
            raise RuntimeError("No video stream in RTSP")

        base_codec = str(getattr(v_stream.codec_context, "name", "") or "h264").lower()
        try:
            from apex_vision.core.dl_engine import get_onnx_execution_capabilities

            has_cuda = bool(get_onnx_execution_capabilities().get("cuda_available", False))
        except Exception:
            has_cuda = False

        candidates: List[str] = []
        if try_hwaccel and base_codec in ("h264", "hevc"):
            if has_cuda and f"{base_codec}_cuvid" in av.codecs_available:
                candidates.append(f"{base_codec}_cuvid")
            if f"{base_codec}_qsv" in av.codecs_available:
                candidates.append(f"{base_codec}_qsv")

        self.decoder_name = base_codec or "av_cpu"
        self._primed_frame: Any = None
        if candidates:
            for cname in candidates:
                test_cont = None
                try:
                    test_cont = av.open(
                        url,
                        options={"rtsp_transport": "tcp", "stimeout": "5000000", "vcodec": cname},
                        timeout=5.0,
                    )
                    ts = next((s for s in test_cont.streams if s.type == "video"), None)
                    if ts is not None:
                        first = next(test_cont.decode(ts))
                        if first is not None:
                            self._container.close()
                            self._container = test_cont
                            v_stream = ts
                            self.decoder_name = cname
                            self._primed_frame = first
                            test_cont = None
                            break
                except Exception:
                    if test_cont is not None:
                        try:
                            test_cont.close()
                        except Exception:
                            pass

        v_stream.thread_type = "AUTO"
        self._stream = v_stream
        self._frame_iter = self._container.decode(self._stream)
        self._grabbed_frame: Any = None
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def grab(self) -> bool:
        if not self._opened:
            return False
        try:
            if self._primed_frame is not None:
                self._grabbed_frame = self._primed_frame
                self._primed_frame = None
                return True
            self._grabbed_frame = next(self._frame_iter)
            return self._grabbed_frame is not None
        except Exception:
            self._grabbed_frame = None
            return False

    def retrieve(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._grabbed_frame is None:
            return False, None
        try:
            bgr = self._grabbed_frame.to_ndarray(format="bgr24")
            self._grabbed_frame = None
            return True, bgr
        except Exception:
            return False, None

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.grab():
            return False, None
        return self.retrieve()

    def release(self) -> None:
        self._opened = False
        self._grabbed_frame = None
        try:
            if self._container is not None:
                self._container.close()
        except Exception:
            pass
        self._container = None


class CameraStreamWorker:
    """Dedicated background capture thread keeping latest frame + rolling 10s compressed ring."""

    def __init__(
        self,
        camera_cfg: Any,
        *,
        ring_buffer_sec: float = 10.0,
        ring_fps: float = 8.0,
        on_health_change: Optional[Callable[[Dict[str, object]], None]] = None,
        decode_backend: str = "auto",
        target_fps: Optional[float] = None,
        idle_ring_fps: float = 2.0,
        ring_max_width: int = 1280,
        sub_stream_url: Optional[str] = None,
    ):
        self._cfg = camera_cfg
        self._ring_fps = max(1.0, float(ring_fps))
        self._ring_min_dt = 1.0 / self._ring_fps
        self._idle_ring_min_dt = 1.0 / max(0.5, float(idle_ring_fps))
        self._target_fps = max(2.0, float(target_fps if target_fps is not None else self._ring_fps))
        self._decode_backend = str(decode_backend or "auto").strip().lower()
        self._decoder_backend = "uninitialized"
        self._ring_max_width = max(0, int(ring_max_width))

        resolved_sub = str(sub_stream_url if sub_stream_url is not None else getattr(camera_cfg, "sub_stream_url", "") or "")
        self._sub_stream_url = _clean_url(resolved_sub)

        maxlen = max(16, int(round(max(2.0, float(ring_buffer_sec)) * self._ring_fps)))
        self._ring: Deque[Tuple[float, bytes]] = deque(maxlen=maxlen)
        self._last_ring_ts = -1e9

        self._lock = threading.RLock()
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sub_thread: Optional[threading.Thread] = None

        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._main_dims: Tuple[int, int] = (0, 0)
        self._seq: int = 0
        self._latest_sub_frame: Optional[np.ndarray] = None
        self._sub_seq: int = 0
        self._loop_count: int = 0
        self._last_capture_wall: float = 0.0

        self._is_local_file: bool = os.path.isfile(_clean_url(camera_cfg.rtsp_url))
        self._clip_detection_done: bool = False
        self._restart_req_token: int = 0
        self._restart_ack_token: int = 0
        self._eof_last_frame: Optional[np.ndarray] = None
        self._eof_ring_snapshot: List[Tuple[float, bytes]] = []
        self._snap_cache: Dict[Tuple[int, int, bool], Tuple[int, Any, bytes]] = {}

        self._state: str = "OFFLINE"
        self._last_error: str = ""
        self._fps_est: float = 0.0
        self._motion_active: bool = False
        self._on_health_change = on_health_change

    @property
    def camera_id(self) -> str:
        return self._cfg.camera_id

    @property
    def loop_count(self) -> int:
        with self._lock:
            return self._loop_count

    @property
    def is_local_file(self) -> bool:
        with self._lock:
            return self._is_local_file

    @property
    def clip_detection_done(self) -> bool:
        with self._lock:
            return self._clip_detection_done

    def set_clip_detection_done(self, done: bool) -> None:
        with self._lock:
            self._clip_detection_done = bool(done)

    @property
    def restart_pending(self) -> bool:
        with self._lock:
            return self._restart_req_token != self._restart_ack_token

    def restart_from_start(self) -> None:
        """Schedule a clean rewind to frame 0 and re-enable Pass 0 detection for local videos."""
        with self._lock:
            self._restart_req_token += 1
            self._clip_detection_done = False
            self._loop_count = 0
            self._eof_last_frame = None
            self._eof_ring_snapshot = []
            self._snap_cache.clear()
            self._ring.clear()
            self._last_ring_ts = -1e9

    def pop_eof_context(self) -> Tuple[Optional[np.ndarray], List[Tuple[float, bytes]]]:
        """Return and clear the final frame + ring buffer snapshot saved right before clip rewind."""
        with self._lock:
            frame = self._eof_last_frame
            ring = self._eof_ring_snapshot
            self._eof_last_frame = None
            self._eof_ring_snapshot = []
            return frame, ring

    @property
    def config(self) -> CameraConfig:
        with self._lock:
            return self._cfg

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"rtsp-{self._cfg.camera_id}",
            daemon=True,
        )
        self._thread.start()
        main_clean = _clean_url(self._cfg.rtsp_url)
        if self._sub_stream_url and self._sub_stream_url != main_clean:
            self._sub_thread = threading.Thread(
                target=self._run_sub_loop,
                name=f"rtsp-sub-{self._cfg.camera_id}",
                daemon=True,
            )
            self._sub_thread.start()

    def stop(self, timeout_sec: float = 3.0) -> None:
        self._stop_evt.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout_sec)
        if self._sub_thread is not None and self._sub_thread.is_alive():
            self._sub_thread.join(timeout=max(0.5, timeout_sec * 0.5))

    def update_config(self, new_cfg: CameraConfig) -> bool:
        """Update config; returns True if stream URL/enabled changed and thread should restart."""
        clean_new = _clean_url(new_cfg.rtsp_url)
        sub_new = _clean_url(str(getattr(new_cfg, "sub_stream_url", "") or ""))
        with self._lock:
            need_restart = (
                clean_new != _clean_url(self._cfg.rtsp_url)
                or sub_new != self._sub_stream_url
                or bool(new_cfg.enabled) != bool(self._cfg.enabled)
            )
            self._cfg = new_cfg
            self._sub_stream_url = sub_new
            self._is_local_file = os.path.isfile(clean_new)
            if need_restart:
                self._clip_detection_done = False
                self._restart_ack_token = self._restart_req_token
                self._loop_count = 0
                self._eof_last_frame = None
                self._eof_ring_snapshot = []
                self._latest_sub_frame = None
                self._snap_cache.clear()
                self._ring.clear()
                self._last_ring_ts = -1e9
        if need_restart:
            self.stop()
            if new_cfg.enabled and clean_new:
                self.start()
        return need_restart

    def set_motion_active(self, active: bool) -> None:
        with self._lock:
            self._motion_active = bool(active)

    def invalidate_snapshot_cache(self) -> None:
        with self._lock:
            self._snap_cache.clear()

    def get_latest_frame(self) -> Tuple[Optional[np.ndarray], float, int]:
        with self._lock:
            if self._latest_frame is None:
                return None, 0.0, self._seq
            return self._latest_frame.copy(), self._latest_ts, self._seq

    def _get_latest_frame_ref(self) -> Tuple[Optional[np.ndarray], float, int]:
        with self._lock:
            return self._latest_frame, self._latest_ts, self._seq

    def snapshot_ring_buffer(self) -> List[Tuple[float, bytes]]:
        with self._lock:
            return list(self._ring)

    def get_snapshot_jpeg(
        self,
        zones: Optional[List[Any]] = None,
        *,
        overlays: bool = False,
        overlay_layers: Any = None,
        overlay_tracks: Optional[Sequence[Dict[str, Any]]] = None,
        overlay_poses: Optional[Sequence[Dict[str, Any]]] = None,
        overlay_bags: Optional[Sequence[Dict[str, Any]]] = None,
        overlay_motion_roi: Optional[Sequence[Any]] = None,
        preview_only: bool = False,
        quality: int = 85,
        max_width: int = 0,
        cache_key: Any = None,
    ) -> Optional[bytes]:
        q = max(40, min(95, int(quality)))
        max_w = max(0, min(3840, int(max_width)))
        active_layers = _parse_overlay_layers(bool(overlays), overlay_layers)
        has_overlays = bool(overlays and active_layers)
        cache_slot = (max_w, q, has_overlays, active_layers)

        raw_frame, _, seq = self._get_latest_frame_ref()
        sub_frame = None
        sub_seq = seq
        main_dims = (0, 0)
        if max_w > 0 and max_w <= 640:
            with self._lock:
                if self._latest_sub_frame is not None:
                    sub_frame = self._latest_sub_frame
                    sub_seq = self._sub_seq
                    main_dims = self._main_dims

        src_frame = sub_frame if sub_frame is not None else raw_frame
        cache_seq = sub_seq if sub_frame is not None else seq
        if src_frame is None:
            return None

        if cache_key is not None:
            with self._lock:
                cached = self._snap_cache.get(cache_slot)
                if cached is not None and cached[0] == cache_seq and cached[1] == cache_key:
                    return cached[2]

        src_h, src_w = src_frame.shape[:2]
        orig_w = main_dims[0] if (sub_frame is not None and main_dims[0] > 0) else src_w
        orig_h = main_dims[1] if (sub_frame is not None and main_dims[1] > 0) else src_h
        if max_w > 0 and src_w > max_w:
            scale = max_w / float(src_w)
            nw = max(2, int(round(src_w * scale)))
            nh = max(2, int(round(src_h * scale)))
            frame = cv2.resize(src_frame, (nw, nh), interpolation=cv2.INTER_AREA)
            sx = nw / float(orig_w)
            sy = nh / float(orig_h)
        elif sub_frame is not None:
            frame = src_frame.copy() if has_overlays else src_frame
            sx = src_w / float(orig_w)
            sy = src_h / float(orig_h)
        else:
            frame = src_frame.copy() if has_overlays else src_frame
            sx = 1.0
            sy = 1.0

        if has_overlays:
            layers_set = set(active_layers)
            h, w = frame.shape[:2]
            thick = max(2, int(round(w / 480.0)))
            font_px = max(11, min(17, int(round(w / 50.0))))

            # 1. Shelf & Aisle ROI Zones
            if zones and ("shelf" in layers_set or "aisle" in layers_set):
                for z in zones:
                    rect, z_role, z_name = _zone_to_rect(z, w, h)
                    if rect is None:
                        continue
                    role_norm = "aisle" if z_role == "aisle" else "shelf"
                    if role_norm not in layers_set:
                        continue
                    x, y, rw, rh = rect
                    x1 = max(0, min(w - 2, x))
                    y1 = max(0, min(h - 2, y))
                    x2 = max(x1 + 2, min(w - 1, x + rw))
                    y2 = max(y1 + 2, min(h - 1, y + rh))
                    if role_norm == "shelf":
                        color = (0, 140, 255)      # Deep Orange
                        pill_bg = (14, 72, 165)
                        txt_col = (255, 255, 255)
                        tag = f"SHELF · {z_name}"
                    else:
                        color = (25, 195, 255)     # Warm Amber-Gold
                        pill_bg = (18, 95, 135)
                        txt_col = (255, 255, 255)
                        tag = f"AISLE · {z_name}"
                    roi_sub = frame[y1:y2, x1:x2]
                    if roi_sub.size > 0:
                        tint = np.empty_like(roi_sub)
                        tint[:] = color
                        cv2.addWeighted(tint, 0.12, roi_sub, 0.88, 0.0, dst=roi_sub)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    _draw_label_pill(
                        frame,
                        tag,
                        x1,
                        y1,
                        pill_bg,
                        txt_col,
                        font_px=max(10, font_px - 1),
                        border_bgr=color,
                        above=True,
                    )

            # 2. Motion Gate ROI
            if "motion" in layers_set and isinstance(overlay_motion_roi, (list, tuple)) and len(overlay_motion_roi) >= 4:
                mx = int(round(float(overlay_motion_roi[0]) * sx))
                my = int(round(float(overlay_motion_roi[1]) * sy))
                mw = int(round(float(overlay_motion_roi[2]) * sx))
                mh = int(round(float(overlay_motion_roi[3]) * sy))
                if mw > 4 and mh > 4:
                    mx1 = max(0, min(w - 2, mx))
                    my1 = max(0, min(h - 2, my))
                    mx2 = max(mx1 + 2, min(w - 1, mx + mw))
                    my2 = max(my1 + 2, min(h - 1, my + mh))
                    m_col = (235, 210, 35)  # Cyan-Teal
                    cv2.rectangle(frame, (mx1, my1), (mx2, my2), m_col, 2)
                    _draw_label_pill(
                        frame,
                        "MOTION ROI",
                        mx1,
                        my1,
                        (85, 75, 12),
                        (255, 255, 255),
                        font_px=max(10, font_px - 1),
                        border_bgr=m_col,
                        above=True,
                    )

            # 3. Context Bags / Objects
            if "bags" in layers_set and overlay_bags:
                bag_col = (220, 80, 235)     # Magenta-Violet
                bag_bg = (115, 28, 130)
                for b in overlay_bags:
                    bb = b.get("Box") or b.get("bbox")
                    if not isinstance(bb, (list, tuple)) or len(bb) < 4:
                        continue
                    bx = int(round(float(bb[0]) * sx))
                    by = int(round(float(bb[1]) * sy))
                    bw = int(round(float(bb[2]) * sx))
                    bh = int(round(float(bb[3]) * sy))
                    if bw <= 2 or bh <= 2:
                        continue
                    bx1 = max(0, min(w - 2, bx))
                    by1 = max(0, min(h - 2, by))
                    bx2 = max(bx1 + 2, min(w - 1, bx + bw))
                    by2 = max(by1 + 2, min(h - 1, by + bh))
                    cls_name = str(b.get("Class") or b.get("label") or "OBJ").upper()
                    b_conf = float(b.get("Score") if b.get("Score") is not None else (b.get("confidence") or 0.0))
                    b_tag = f"{cls_name} {int(round(b_conf * 100))}%" if b_conf > 0 else cls_name
                    cv2.rectangle(frame, (bx1, by1), (bx2, by2), bag_col, 2)
                    _draw_label_pill(
                        frame,
                        b_tag,
                        bx1,
                        by1,
                        bag_bg,
                        (255, 255, 255),
                        font_px=max(10, font_px - 1),
                        border_bgr=bag_col,
                        above=True,
                    )

            # 4. YOLO Pose (Person Pose Box + 17-Keypoint Skeleton)
            if "pose" in layers_set:
                pose_items = list(overlay_poses or ())
                if not pose_items and overlay_tracks:
                    pose_items = [
                        {
                            "Box": tr.get("bbox"),
                            "Score": tr.get("confidence", 0.0),
                            "Keypoints": tr.get("keypoints") or [],
                        }
                        for tr in overlay_tracks
                    ]
                pose_box_col = (255, 195, 65)   # Sky Blue
                skel_col = (120, 245, 130)      # Mint-Lime
                joint_col = (50, 220, 255)      # Warm Yellow
                botsort_on = "botsort" in layers_set
                for p in pose_items:
                    p_box = p.get("Box") or p.get("bbox")
                    if isinstance(p_box, (list, tuple)) and len(p_box) >= 4:
                        px = int(round(float(p_box[0]) * sx))
                        py = int(round(float(p_box[1]) * sy))
                        pw = int(round(float(p_box[2]) * sx))
                        ph = int(round(float(p_box[3]) * sy))
                        if pw > 2 and ph > 2:
                            px1 = max(0, min(w - 2, px))
                            py1 = max(0, min(h - 2, py))
                            px2 = max(px1 + 2, min(w - 1, px + pw))
                            py2 = max(py1 + 2, min(h - 1, py + ph))
                            cv2.rectangle(frame, (px1, py1), (px2, py2), pose_box_col, 1 if botsort_on else 2)
                            p_score = float(p.get("Score") if p.get("Score") is not None else (p.get("confidence") or 0.0))
                            p_label = f"POSE {int(round(p_score * 100))}%" if p_score > 0 else "POSE"
                            _draw_label_pill(
                                frame,
                                p_label,
                                px1,
                                py2 if botsort_on else py1,
                                (110, 72, 16),
                                (255, 255, 255),
                                font_px=max(10, font_px - 1),
                                border_bgr=pose_box_col,
                                above=not botsort_on,
                            )
                    kps = p.get("Keypoints") or p.get("keypoints") or []
                    if isinstance(kps, (list, tuple)) and len(kps) >= 17:
                        for idx_a, idx_b in _SKELETON_EDGES:
                            ka, kb = kps[idx_a], kps[idx_b]
                            if (
                                len(ka) >= 3
                                and len(kb) >= 3
                                and float(ka[2]) >= 0.30
                                and float(kb[2]) >= 0.30
                                and float(ka[0]) > 0
                                and float(kb[0]) > 0
                            ):
                                pt1 = (int(round(float(ka[0]) * sx)), int(round(float(ka[1]) * sy)))
                                pt2 = (int(round(float(kb[0]) * sx)), int(round(float(kb[1]) * sy)))
                                cv2.line(frame, pt1, pt2, skel_col, max(1, thick - 1), cv2.LINE_AA)
                        for kp in kps[:17]:
                            if len(kp) >= 3 and float(kp[2]) >= 0.30 and float(kp[0]) > 0:
                                jpt = (int(round(float(kp[0]) * sx)), int(round(float(kp[1]) * sy)))
                                cv2.circle(frame, jpt, max(2, thick), joint_col, -1, cv2.LINE_AA)

            # 5. BoT-SORT Tracks, Corner Brackets, Motion Trails & Behavior State Badges
            if "botsort" in layers_set and overlay_tracks:
                for tr in overlay_tracks:
                    bb = tr.get("bbox")
                    if not isinstance(bb, (list, tuple)) or len(bb) < 4:
                        continue
                    x = int(round(float(bb[0]) * sx))
                    y = int(round(float(bb[1]) * sy))
                    bw = int(round(float(bb[2]) * sx))
                    bh = int(round(float(bb[3]) * sy))
                    if bw <= 2 or bh <= 2:
                        continue
                    x1 = max(0, min(w - 2, x))
                    y1 = max(0, min(h - 2, y))
                    x2 = max(x1 + 2, min(w - 1, x + bw))
                    y2 = max(y1 + 2, min(h - 1, y + bh))

                    tid = int(tr.get("track_id", 0))
                    conf = float(tr.get("confidence") or 0.0)
                    phase = str(tr.get("phase") or "").upper()
                    armed = bool(tr.get("armed"))

                    if armed:
                        box_bgr = (68, 63, 244)       # Rose/Red
                        pill_bgr = (45, 22, 175)      # Deep Crimson
                        txt_bgr = (255, 255, 255)
                        label = f"BOT-SORT #{tid} · ARMED"
                    elif phase in ("REACH", "TUCK", "BLADED", "CROUCH"):
                        box_bgr = (11, 158, 245)      # Amber
                        pill_bgr = (10, 115, 195)
                        txt_bgr = (255, 255, 255)
                        label = f"BOT-SORT #{tid} · {phase}"
                    elif preview_only:
                        box_bgr = (248, 189, 56)      # Sky Cyan
                        pill_bgr = (145, 98, 18)
                        txt_bgr = (255, 255, 255)
                        label = f"BOT-SORT #{tid}" if conf <= 0 else f"BOT-SORT #{tid} · {int(round(conf * 100))}%"
                    else:
                        box_bgr = (129, 185, 16)      # Emerald
                        pill_bgr = (72, 115, 12)
                        txt_bgr = (255, 255, 255)
                        label = f"BOT-SORT #{tid}" if conf <= 0 else f"BOT-SORT #{tid} · {int(round(conf * 100))}%"

                    cv2.rectangle(frame, (x1, y1), (x2, y2), box_bgr, thick)
                    # Crisp corner brackets
                    clen = max(10, min(x2 - x1, y2 - y1) // 4)
                    c_thick = thick + 1
                    for px, py, dx, dy in (
                        (x1, y1, 1, 1),
                        (x2, y1, -1, 1),
                        (x1, y2, 1, -1),
                        (x2, y2, -1, -1),
                    ):
                        cv2.line(frame, (px, py), (px + dx * clen, py), box_bgr, c_thick, cv2.LINE_AA)
                        cv2.line(frame, (px, py), (px, py + dy * clen), box_bgr, c_thick, cv2.LINE_AA)

                    trail = tr.get("trail")
                    if isinstance(trail, (list, tuple)) and len(trail) >= 2:
                        pts = [
                            (int(round(float(pt[0]) * sx)), int(round(float(pt[1]) * sy)))
                            for pt in trail
                            if isinstance(pt, (list, tuple)) and len(pt) >= 2
                        ]
                        for j in range(1, len(pts)):
                            cv2.line(frame, pts[j - 1], pts[j], box_bgr, max(1, thick - 1), cv2.LINE_AA)

                    _draw_label_pill(
                        frame,
                        label,
                        x1,
                        y1,
                        pill_bgr,
                        txt_bgr,
                        font_px=font_px,
                        border_bgr=box_bgr,
                        above=True,
                    )

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if not ok:
            return None
        jpg_bytes = buf.tobytes()
        if cache_key is not None:
            with self._lock:
                cur_seq = self._sub_seq if sub_frame is not None else self._seq
                if cur_seq == cache_seq:
                    if len(self._snap_cache) >= 8 and cache_slot not in self._snap_cache:
                        self._snap_cache.pop(next(iter(self._snap_cache)), None)
                    self._snap_cache[cache_slot] = (cache_seq, cache_key, jpg_bytes)
        return jpg_bytes

    def get_health(self) -> Dict[str, object]:
        with self._lock:
            age_ms = (
                int(max(0.0, (time.monotonic() - self._last_capture_wall) * 1000.0))
                if self._last_capture_wall > 0.0
                else -1
            )
            return {
                "camera_id": self._cfg.camera_id,
                "state": self._state,
                "fps": round(self._fps_est, 1),
                "motion_active": self._motion_active,
                "last_frame_age_ms": age_ms,
                "error": self._last_error,
                "is_local_file": self._is_local_file,
                "clip_detection_done": self._clip_detection_done,
                "loop_count": self._loop_count,
                "decoder_backend": self._decoder_backend,
            }

    def _set_state(self, state: str, error: str = "") -> None:
        emit = False
        with self._lock:
            if state != self._state or (error and error != self._last_error):
                self._state = state
                self._last_error = error
                emit = True
            else:
                self._last_error = error
        if emit and self._on_health_change is not None:
            try:
                self._on_health_change(self.get_health())
            except Exception:
                pass

    def _run_loop(self) -> None:
        backoff_steps = (1.0, 2.0, 5.0, 10.0)
        fail_count = 0

        while not self._stop_evt.is_set():
            url = _clean_url(self._cfg.rtsp_url)
            if not self._cfg.enabled or not url:
                self._set_state("OFFLINE", "Camera disabled or RTSP URL empty")
                self._stop_evt.wait(1.0)
                continue

            is_file = os.path.isfile(url)
            if is_file:
                cap = cv2.VideoCapture(url)
                dec_name = "opencv_file"
            else:
                cap, dec_name = _open_rtsp_capture(url, self._decode_backend)
            with self._lock:
                self._decoder_backend = dec_name

            if not cap.isOpened():
                cap.release()
                fail_count += 1
                self._set_state("OFFLINE", f"Failed to open {mask_rtsp_url(url)}")
                wait_s = backoff_steps[min(fail_count - 1, len(backoff_steps) - 1)]
                self._stop_evt.wait(wait_s)
                continue

            fail_count = 0
            with self._lock:
                self._is_local_file = is_file
            self._set_state("ONLINE", "")
            src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) if is_file else 0.0
            frame_period = (1.0 / max(1.0, min(30.0, src_fps))) if src_fps > 0.0 else 0.0
            fps_window_t = time.monotonic()
            fps_frames = 0
            last_retrieve_wall = 0.0

            try:
                while not self._stop_evt.is_set():
                    t_loop = time.monotonic()
                    with self._lock:
                        req_tok = self._restart_req_token
                        restart_now = req_tok != self._restart_ack_token
                        motion_now = self._motion_active
                        if restart_now:
                            self._clip_detection_done = False
                            self._loop_count = 0
                            self._eof_last_frame = None
                            self._eof_ring_snapshot = []
                            self._ring.clear()
                            self._last_ring_ts = -1e9
                    if is_file:
                        if restart_now:
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = cap.read()
                    else:
                        if not cap.grab():
                            ret, frame = False, None
                        else:
                            now_g = time.monotonic()
                            active_dt = 1.0 / max(4.0, min(15.0, self._target_fps * 1.25))
                            idle_dt = 1.0 / max(3.0, min(8.0, self._target_fps))
                            min_dt = active_dt if motion_now else idle_dt
                            if last_retrieve_wall > 0.0 and (now_g - last_retrieve_wall) < min_dt:
                                continue
                            ret, frame = cap.retrieve()
                            if ret and frame is not None:
                                last_retrieve_wall = now_g

                    if not ret or frame is None:
                        if is_file:
                            with self._lock:
                                self._eof_last_frame = self._latest_frame.copy() if self._latest_frame is not None else None
                                self._eof_ring_snapshot = list(self._ring)
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ret, frame = cap.read()
                            if ret and frame is not None:
                                with self._lock:
                                    self._ring.clear()
                                    self._last_ring_ts = -1e9
                                    self._loop_count += 1
                        if not ret or frame is None:
                            self._set_state("RECONNECTING", f"Stream read error ({mask_rtsp_url(url)})")
                            break

                    wall_now = time.monotonic()
                    if is_file and src_fps > 0.0:
                        pos_frames = float(cap.get(cv2.CAP_PROP_POS_FRAMES) or 0.0)
                        pos_msec = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
                        ts = max(0.0, (pos_frames - 1.0) / src_fps) if pos_frames >= 1.0 else (pos_msec / 1000.0)
                    else:
                        ts = wall_now

                    fps_frames += 1
                    dt_fps = wall_now - fps_window_t
                    if dt_fps >= 2.0:
                        with self._lock:
                            self._fps_est = fps_frames / dt_fps
                        fps_frames = 0
                        fps_window_t = wall_now

                    with self._lock:
                        self._latest_frame = frame
                        self._latest_ts = ts
                        self._main_dims = (frame.shape[1], frame.shape[0])
                        self._seq += 1
                        self._last_capture_wall = wall_now
                        if restart_now:
                            self._restart_ack_token = req_tok

                    eff_ring_dt = self._ring_min_dt if (is_file or motion_now) else self._idle_ring_min_dt
                    if (wall_now - self._last_ring_ts) >= eff_ring_dt:
                        ring_frame = frame
                        if self._ring_max_width > 0 and ring_frame.shape[1] > self._ring_max_width:
                            rh, rw = ring_frame.shape[:2]
                            rscale = self._ring_max_width / float(rw)
                            ring_frame = cv2.resize(
                                ring_frame,
                                (self._ring_max_width, max(2, int(round(rh * rscale)))),
                                interpolation=cv2.INTER_AREA,
                            )
                        ok_j, buf = cv2.imencode(".jpg", ring_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                        if ok_j:
                            with self._lock:
                                self._ring.append((ts, buf.tobytes()))
                            self._last_ring_ts = wall_now

                    if is_file and frame_period > 0.0:
                        elapsed = time.monotonic() - t_loop
                        if elapsed < frame_period:
                            self._stop_evt.wait(frame_period - elapsed)
            finally:
                cap.release()

            if not self._stop_evt.is_set():
                fail_count += 1
                wait_s = backoff_steps[min(fail_count - 1, len(backoff_steps) - 1)]
                self._stop_evt.wait(wait_s)

    def _run_sub_loop(self) -> None:
        """Lightweight grabber for optional SD sub-stream used by Live Grid tiles."""
        backoff_steps = (1.0, 2.0, 5.0)
        fail_count = 0
        while not self._stop_evt.is_set():
            sub_url = self._sub_stream_url
            if not sub_url or not self._cfg.enabled:
                self._stop_evt.wait(1.0)
                continue
            cap, _ = _open_rtsp_capture(sub_url, self._decode_backend)
            if not cap.isOpened():
                cap.release()
                fail_count += 1
                self._stop_evt.wait(backoff_steps[min(fail_count - 1, len(backoff_steps) - 1)])
                continue
            fail_count = 0
            last_sub_wall = 0.0
            try:
                while not self._stop_evt.is_set():
                    if not cap.grab():
                        break
                    now_s = time.monotonic()
                    if last_sub_wall > 0.0 and (now_s - last_sub_wall) < 0.08:
                        continue
                    ok_s, sframe = cap.retrieve()
                    if not ok_s or sframe is None:
                        break
                    last_sub_wall = now_s
                    with self._lock:
                        self._latest_sub_frame = sframe
                        self._sub_seq += 1
            finally:
                cap.release()
