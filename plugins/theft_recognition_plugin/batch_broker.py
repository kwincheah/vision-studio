"""Cross-camera micro-batch ONNX broker for coalescing concurrent camera frames into one GPU/CPU batch."""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Tuple

import numpy as np


class DynamicBatchBroker:
    """Coalesces concurrent (1, C, H, W) blobs into (N, C, H, W) batches up to `max_batch` or `max_wait_ms`."""

    def __init__(
        self,
        run_batch_fn: Callable[[np.ndarray], np.ndarray],
        *,
        max_batch: int = 8,
        max_wait_ms: float = 8.0,
        supports_dynamic_batch: bool = True,
        name: str = "onnx_batch_broker",
    ):
        self._run_batch_fn = run_batch_fn
        self._max_batch = max(1, int(max_batch))
        self._max_wait_sec = max(0.0, float(max_wait_ms)) / 1000.0
        self._supports_dynamic_batch = bool(supports_dynamic_batch)
        self._name = str(name)

        self._cv = threading.Condition()
        self._direct_lock = threading.Lock()
        self._queue: Deque[Tuple[np.ndarray, Future]] = deque()
        self._worker: Optional[threading.Thread] = None
        self._stop = False

        self._total_requests = 0
        self._total_batches = 0
        self._max_batch_seen = 0

    @property
    def supports_dynamic_batch(self) -> bool:
        return self._supports_dynamic_batch

    def configure(self, *, max_batch: Optional[int] = None, max_wait_ms: Optional[float] = None) -> None:
        with self._cv:
            if max_batch is not None:
                self._max_batch = max(1, int(max_batch))
            if max_wait_ms is not None:
                self._max_wait_sec = max(0.0, float(max_wait_ms)) / 1000.0
            self._cv.notify_all()

    def get_metrics(self) -> Dict[str, float | int | bool]:
        with self._cv:
            reqs = int(self._total_requests)
            batches = int(self._total_batches)
            avg = round(float(reqs) / float(batches), 2) if batches > 0 else 0.0
            return {
                "supports_dynamic_batch": self._supports_dynamic_batch,
                "max_batch": self._max_batch,
                "max_wait_ms": round(self._max_wait_sec * 1000.0, 2),
                "total_requests": reqs,
                "total_batches": batches,
                "max_batch_seen": int(self._max_batch_seen),
                "avg_batch_size": avg,
            }

    def _ensure_worker_locked(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._stop = False
            self._worker = threading.Thread(target=self._loop, name=self._name, daemon=True)
            self._worker.start()

    @staticmethod
    def _to_4d(blob: np.ndarray) -> np.ndarray:
        arr = np.asarray(blob, dtype=np.float32)
        if arr.ndim == 3:
            return arr[None, ...]
        return arr

    def submit(self, blob: np.ndarray, *, coalesce: bool = True) -> np.ndarray:
        """Submit one (1, C, H, W) tensor and return its corresponding (1, ...) output slice."""
        arr4 = self._to_4d(blob)
        if not self._supports_dynamic_batch or self._max_batch <= 1 or not coalesce:
            with self._direct_lock:
                raw = np.asarray(self._run_batch_fn(arr4))
            with self._cv:
                self._total_requests += 1
                self._total_batches += 1
                if self._max_batch_seen < 1:
                    self._max_batch_seen = 1
            return raw

        fut: Future = Future()
        with self._cv:
            self._ensure_worker_locked()
            self._queue.append((arr4[0], fut))
            self._cv.notify_all()
        return fut.result()

    def infer_batch(self, blobs: List[np.ndarray]) -> List[np.ndarray]:
        """Synchronously execute an explicit batch of blobs (chunks cleanly if fixed batch=1)."""
        if not blobs:
            return []
        if not self._supports_dynamic_batch or len(blobs) == 1:
            outs: List[np.ndarray] = []
            with self._direct_lock:
                for b in blobs:
                    outs.append(np.asarray(self._run_batch_fn(self._to_4d(b))))
            with self._cv:
                self._total_requests += len(blobs)
                self._total_batches += len(blobs)
                self._max_batch_seen = max(self._max_batch_seen, 1)
            return outs

        stacked = np.stack([self._to_4d(b)[0] for b in blobs], axis=0)
        with self._direct_lock:
            raw = np.asarray(self._run_batch_fn(stacked))
        n = len(blobs)
        with self._cv:
            self._total_requests += n
            self._total_batches += 1
            if n > self._max_batch_seen:
                self._max_batch_seen = n
        return [raw[i : i + 1] for i in range(n)]

    def _loop(self) -> None:
        while True:
            batch: List[Tuple[np.ndarray, Future]] = []
            with self._cv:
                while not self._queue and not self._stop:
                    self._cv.wait(timeout=0.5)
                if self._stop and not self._queue:
                    return

                max_b = self._max_batch
                wait_s = self._max_wait_sec
                if len(self._queue) < max_b and wait_s > 0.0:
                    deadline = time.monotonic() + wait_s
                    while len(self._queue) < max_b and not self._stop:
                        rem = deadline - time.monotonic()
                        if rem <= 0.0:
                            break
                        self._cv.wait(timeout=rem)

                while self._queue and len(batch) < max_b:
                    batch.append(self._queue.popleft())

            if not batch:
                continue

            stacked = np.stack([item[0] for item in batch], axis=0)
            n = len(batch)
            try:
                with self._direct_lock:
                    raw = np.asarray(self._run_batch_fn(stacked))
                with self._cv:
                    self._total_requests += n
                    self._total_batches += 1
                    if n > self._max_batch_seen:
                        self._max_batch_seen = n
                for idx, (_, fut) in enumerate(batch):
                    if not fut.done():
                        fut.set_result(raw[idx : idx + 1])
            except Exception as exc:
                for _, fut in batch:
                    if not fut.done():
                        fut.set_exception(exc)

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=1.5)
