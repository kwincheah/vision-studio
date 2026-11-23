"""
Native C++17 Core Bridge (`_apex_core`) with seamless pure-Python fallback.

When compiled (standard on Windows/macOS release builds), `_apex_core` executes
DAG topological sorting, cycle analysis, pre-allocated camera frame ring buffers,
YOLO box decoding / batched NMS, and optical image diagnostics in C++17 with the
Python GIL released.

On platforms running directly from source without a C++ build (e.g., macOS
source development), all functions transparently fall back to pure Python.
"""
from collections import deque
import os
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

try:
    from apex_vision import _apex_core as _CORE
except ImportError:
    _CORE = None


def is_native_active() -> bool:
    """True when the compiled C++17 `_apex_core` extension is loaded."""
    return _CORE is not None


def native_info() -> Dict[str, Any]:
    """Return compiler/runtime metadata for diagnostics and tests."""
    if _CORE is not None:
        info = dict(_CORE.build_info())
        info["active"] = True
        info["mode"] = "C++17 Hybrid"
        return info
    return {
        "active": False,
        "mode": "Pure Python Fallback",
        "compiler": "Python",
        "hardware_concurrency": os.cpu_count() or 1,
    }


def kahn_sort(ids: List[str], edges: List[Tuple[str, str]]) -> List[str]:
    if _CORE is not None:
        return _CORE.kahn_sort(ids, edges)
    adj: Dict[str, List[str]] = {n: [] for n in ids}
    indeg: Dict[str, int] = {n: 0 for n in ids}
    for a, b in edges:
        if a in adj and b in indeg and a != b:
            adj[a].append(b)
            indeg[b] += 1
    queue = deque([n for n in ids if indeg[n] == 0])
    order: List[str] = []
    seen = set()
    while queue:
        cur = queue.popleft()
        seen.add(cur)
        order.append(cur)
        for nxt in adj.get(cur, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    order += [n for n in ids if n not in seen]
    return order


def find_cycle_nodes(ids: List[str], edges: List[Tuple[str, str]]) -> List[str]:
    if _CORE is not None:
        return _CORE.find_cycle_nodes(ids, edges)
    adj: Dict[str, List[str]] = {n: [] for n in ids}
    for a, b in edges:
        if a in adj and b in adj:
            adj[a].append(b)
    state: Dict[str, int] = {n: 0 for n in ids}
    in_cycle = set()
    for start in ids:
        if state[start] != 0:
            continue
        state[start] = 1
        stack = [(start, 0)]
        while stack:
            u, idx = stack[-1]
            nbrs = adj[u]
            if idx < len(nbrs):
                stack[-1] = (u, idx + 1)
                v = nbrs[idx]
                if state[v] == 1:
                    in_cycle.add(u)
                    in_cycle.add(v)
                elif state[v] == 0:
                    state[v] = 1
                    stack.append((v, 0))
            else:
                state[u] = 2
                stack.pop()
    return [n for n in ids if n in in_cycle]


def compute_execution_waves(order: List[str], edges: List[Tuple[str, str]]) -> List[List[str]]:
    if _CORE is not None:
        return _CORE.compute_execution_waves(order, edges)
    if not order:
        return []
    pos = {nid: i for i, nid in enumerate(order)}
    parents: Dict[int, List[int]] = {i: [] for i in range(len(order))}
    for a, b in edges:
        ia, ib = pos.get(a), pos.get(b)
        if ia is not None and ib is not None and ia < ib:
            parents[ib].append(ia)
    levels = [0] * len(order)
    for i in range(len(order)):
        levels[i] = max((levels[p] + 1 for p in parents[i]), default=0)
    max_lvl = max(levels)
    waves: List[List[str]] = [[] for _ in range(max_lvl + 1)]
    for i, nid in enumerate(order):
        waves[levels[i]].append(nid)
    return waves


def nms_batched(
    boxes_xywh: np.ndarray,
    scores: np.ndarray,
    classes: np.ndarray,
    iou_thresh: float,
    max_det: int,
) -> Optional[List[int]]:
    """Run C++17 GIL-free batched NMS, or return None if native core is unavailable."""
    if _CORE is None:
        return None
    if len(boxes_xywh) == 0:
        return []
    b = np.ascontiguousarray(boxes_xywh, dtype=np.float32)
    s = np.ascontiguousarray(scores, dtype=np.float32)
    c = np.ascontiguousarray(classes, dtype=np.int32)
    return _CORE.nms_batched(b, s, c, float(iou_thresh), int(max_det))


def decode_yolo_matrix(
    out: np.ndarray,
    conf_thresh: float,
    iou_thresh: float,
    max_det: int,
    num_classes: Optional[int],
    scale_x: float,
    scale_y: float,
    pad_x: float,
    pad_y: float,
    orig_w: int,
    orig_h: int,
) -> Optional[List[Dict[str, Any]]]:
    """Run C++17 GIL-free YOLO detection decoding + NMS, or return None if fallback needed."""
    if _CORE is None:
        return None
    arr = np.ascontiguousarray(out, dtype=np.float32)
    return _CORE.decode_yolo_matrix(
        arr,
        float(conf_thresh),
        float(iou_thresh),
        int(max_det),
        int(num_classes) if num_classes is not None else 0,
        float(scale_x),
        float(scale_y),
        float(pad_x),
        float(pad_y),
        int(orig_w),
        int(orig_h),
    )


def compute_optical_stats(img: np.ndarray) -> Dict[str, Any]:
    if _CORE is not None:
        arr = np.ascontiguousarray(img, dtype=np.uint8)
        return _CORE.compute_optical_stats(arr)
    import cv2
    if img is None or img.size == 0:
        return {"mean_brightness": 0.0, "min_val": 0, "max_val": 0,
                "saturated_ratio": 0.0, "dark_ratio": 0.0, "laplacian_variance": 0.0}
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    total = float(gray.size)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return {
        "mean_brightness": float(gray.mean()),
        "min_val": int(gray.min()),
        "max_val": int(gray.max()),
        "saturated_ratio": float((gray >= 250).sum()) / total,
        "dark_ratio": float((gray <= 10).sum()) / total,
        "laplacian_variance": float(lap.var()),
    }


def compute_union_box(boxes: Sequence[Sequence[int]]) -> List[int]:
    if not boxes:
        return [0, 0, 0, 0]
    if _CORE is not None:
        norm = [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in boxes]
        return list(_CORE.compute_union_box(norm))
    min_x = min(int(b[0]) for b in boxes)
    min_y = min(int(b[1]) for b in boxes)
    max_x = max(int(b[0]) + int(b[2]) for b in boxes)
    max_y = max(int(b[1]) + int(b[3]) for b in boxes)
    return [min_x, min_y, max(0, max_x - min_x), max(0, max_y - min_y)]


class _PyFrameRingBuffer:
    """Thread-safe pure-Python fallback matching `_apex_core.FrameRingBuffer`."""

    def __init__(self, capacity: int = 4, reserve_bytes: int = 0):
        self._cap = max(1, int(capacity))
        self._lock = threading.Lock()
        self._buf: List[Optional[Tuple[np.ndarray, Dict[str, Any]]]] = []
        self._latest: Optional[Tuple[np.ndarray, Dict[str, Any]]] = None
        self._total = 0
        self._dropped = 0

    def push(self, frame: np.ndarray, frame_id: int = 0, timestamp_s: float = 0.0) -> None:
        copy = np.ascontiguousarray(frame, dtype=np.uint8).copy()
        meta = {"frame_id": int(frame_id), "timestamp_s": float(timestamp_s)}
        with self._lock:
            self._latest = (copy, meta)
            self._total += 1
            if len(self._buf) >= self._cap:
                self._buf.pop(0)
                self._dropped += 1
            self._buf.append((copy, meta))

    def latest(self):
        with self._lock:
            if self._latest is None:
                return None
            arr, meta = self._latest
            return arr.copy(), dict(meta)

    def pop(self):
        with self._lock:
            if not self._buf:
                return None
            return self._buf.pop(0)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._latest = None

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "capacity": self._cap,
                "count": len(self._buf),
                "total_pushed": self._total,
                "dropped": self._dropped,
            }


def create_ring_buffer(capacity: int = 4, reserve_bytes: int = 0):
    """Instantiate a C++ `FrameRingBuffer` (or Python fallback if unbuilt)."""
    if _CORE is not None:
        return _CORE.FrameRingBuffer(int(capacity), int(reserve_bytes))
    return _PyFrameRingBuffer(capacity, reserve_bytes)
