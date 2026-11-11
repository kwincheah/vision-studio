"""Named data queues that flows (and flows in different solutions' threads) can send into and receive from.

The guide's Send Data / Receive Data modules can use a "data queue" as a way to hand results from one flow to another. Each queue is
first-in first-out and keeps at most ``maxlen`` items (the oldest are dropped).
"""
import threading
from collections import deque
from typing import Any, Deque, Dict, List

_LOCK = threading.Lock()
_QUEUES: Dict[str, Deque[Any]] = {}
DEFAULT_MAXLEN = 1000


def push(name: str, value: Any, maxlen: int = DEFAULT_MAXLEN) -> int:
    """Add ``value`` to queue ``name``; returns the queue's length afterwards."""
    with _LOCK:
        q = _QUEUES.get(name)
        if q is None or q.maxlen != maxlen:
            q = deque(q or [], maxlen=max(1, int(maxlen)))
            _QUEUES[name] = q
        q.append(value)
        return len(q)


def pop(name: str, default: Any = None) -> Any:
    with _LOCK:
        q = _QUEUES.get(name)
        return q.popleft() if q else default


def peek(name: str, default: Any = None) -> Any:
    with _LOCK:
        q = _QUEUES.get(name)
        return q[0] if q else default


def size(name: str) -> int:
    with _LOCK:
        return len(_QUEUES.get(name, ()))


def clear(name: str = "") -> None:
    """Empty one queue, or all of them when no name is given."""
    with _LOCK:
        if name:
            _QUEUES.pop(name, None)
        else:
            _QUEUES.clear()


def names() -> List[str]:
    with _LOCK:
        return sorted(_QUEUES)
