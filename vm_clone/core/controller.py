"""Front-end independent application logic.

Both user interfaces (the widget window in ``vm_clone/ui`` and the QML one in ``qml/``) drive
the same three objects, so a behaviour is implemented - and fixed - exactly once:

* :class:`ImagePool`     - the ordered list of images the Image Source can be fed from.
* :class:`RunEngine`     - runs the active flow on a worker thread and implements Run all,
                           Loop, Stop, queued runs and the continuous-mode image cycling.
* :class:`ProjectState`  - the file a solution came from, change tracking and save / open.

Nothing here imports a widget; the only Qt used is ``QObject`` signals and ``QTimer``.
"""
import json
import os
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from vm_clone.core.base_tool import ToolStatus
from vm_clone.core.imageio import imread

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def natural_key(name: str):
    """Sort key giving ``img2`` before ``img10``."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


# =============================================================================
# Image pool
# =============================================================================
class ImagePool:
    """Images that can be fed to the flow's Image Source, plus the selected one."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []   # {"name", "path", "image"}
        self.index = 0

    def __len__(self) -> int:
        return len(self.items)

    @property
    def names(self) -> List[str]:
        return [i["name"] for i in self.items]

    def clear(self) -> None:
        self.items.clear()
        self.index = 0

    def add_array(self, img: np.ndarray, name: Optional[str] = None) -> int:
        name = name or f"Image_{len(self.items) + 1}"
        for i, item in enumerate(self.items):
            if item.get("path") is None and item["name"] == name:
                item["image"] = img
                self.index = i
                return i
        self.items.append({"name": name, "path": None, "image": img})
        self.index = len(self.items) - 1
        return self.index

    def add_path(self, path: str, name: Optional[str] = None) -> Tuple[Optional[int], str]:
        """Decode ``path`` and add it. Returns ``(index, "")`` or ``(None, reason)``."""
        clean = (path or "").strip().strip('"').strip("'")
        if not clean or not os.path.exists(clean):
            return None, f"Image file not found: {path}"
        full = os.path.abspath(clean)
        img = imread(full)
        if img is None:
            return None, f"Could not decode image: {path}"
        for i, item in enumerate(self.items):
            if item.get("path") == full:
                item["image"] = img
                self.index = i
                return i, ""
        self.items.append({"name": name or os.path.basename(full), "path": full, "image": img})
        self.index = len(self.items) - 1
        return self.index, ""

    def add_folder(self, folder: str, limit: int = 1000,
                   progress: Optional[Callable[[int, int], None]] = None) -> Tuple[int, int, int]:
        """Add every image in ``folder`` (natural name order). Returns ``(added, skipped, failed)``.

        Raises ``OSError`` when the folder cannot be read.
        """
        names = sorted((n for n in os.listdir(folder)
                        if n.lower().endswith(IMAGE_EXTENSIONS)
                        and os.path.isfile(os.path.join(folder, n))), key=natural_key)
        skipped = max(0, len(names) - limit)
        names = names[:limit]
        added = 0
        first: Optional[int] = None
        for i, name in enumerate(names):
            idx, _err = self.add_path(os.path.join(folder, name))
            if idx is not None:
                added += 1
                if first is None:
                    first = idx
            if progress is not None and i % 10 == 0:
                progress(i + 1, len(names))
        if first is not None:
            self.index = first
        return added, skipped, len(names) - added

    def select(self, row: int) -> bool:
        if 0 <= row < len(self.items):
            self.index = row
            return True
        return False

    def apply_to(self, pipeline, row: Optional[int] = None) -> bool:
        """Make pool image ``row`` (default: the selected one) the Image Source's input."""
        row = self.index if row is None else row
        if not self.select(row):
            return False
        item = self.items[row]
        for node in pipeline.nodes.values():
            if node.tool_name == "Image Source":
                if item.get("path"):
                    node.set_param("source_type", "File")
                    node.set_param("file_path", item["path"])
                node._override_image = item.get("image")
                node._override_name = item["name"]
                break
        return True


# =============================================================================
# Run engine
# =============================================================================
class RunEngine(QObject):
    """Executes flows off the calling thread and orchestrates Run all / Loop / Stop.

    Signals (always delivered on the thread that owns this object):
        cycle_finished(payload)  a cycle ended - show the results (``payload`` from compute_cycle)
        cycle_started()          a cycle began
        state_changed()          busy / running / stopping flags changed - refresh buttons
        image_selected(int)      the engine moved the pool selection (batch, loop, auto-cycle)
        progress(str)            human-readable progress ("Loop pass 2: image 1/5 - a.png")
        run_finished(str)        a Run all / Loop run ended; text summarises it
    """

    cycle_finished = pyqtSignal(object)
    cycle_started = pyqtSignal()
    state_changed = pyqtSignal()
    image_selected = pyqtSignal(int)
    progress = pyqtSignal(str)
    run_finished = pyqtSignal(str)
    _worker_done = pyqtSignal()

    def __init__(self, get_pipeline: Callable[[], Any], get_solution: Callable[[], Any],
                 pool: ImagePool, is_async: Callable[[], bool] = lambda: True,
                 timer_active: Callable[[], bool] = lambda: False,
                 interval_ms: Callable[[], int] = lambda: 0, parent=None) -> None:
        super().__init__(parent)
        self._get_pipeline, self._get_solution = get_pipeline, get_solution
        self.pool = pool
        self._is_async, self._timer_active, self._interval_ms = is_async, timer_active, interval_ms
        self.busy = False
        self.pending = False
        self.strip_active = False        # a Run-button run (single, batch or loop) is in progress
        self.stopping = False
        self.batch: Optional[Dict[str, Any]] = None
        self.ticks = 0
        self._thread: Optional[threading.Thread] = None
        self._payload: Optional[dict] = None
        self._worker_done.connect(self._on_worker_done)

    # ------------------------------------------------------------------ execution
    @staticmethod
    def compute_cycle(pipeline, solution) -> dict:
        """One cycle. Touches only core objects, never a widget."""
        import time
        t0 = time.perf_counter()
        try:
            results = pipeline.execute_flow(global_vars=solution.global_variables)
            script_error = solution.run_global_script(results)
            failure = None
        except Exception as exc:  # a bug in the engine must not kill the worker silently
            results, script_error, failure = {}, None, f"{type(exc).__name__}: {exc}"
        return {"pipeline": pipeline, "results": results, "script_error": script_error,
                "failure": failure, "total_ms": (time.perf_counter() - t0) * 1000.0}

    @staticmethod
    def payload_ok(payload: dict) -> bool:
        return not any(r.status == ToolStatus.NG for r in payload["results"].values())

    def request_run(self) -> None:
        """Run the active flow now - asynchronously unless the host disabled it."""
        if not self._is_async():
            self._finish(self.compute_cycle(self._get_pipeline(), self._get_solution()))
            return
        if self.busy:
            self.pending = True          # coalesce: one more run once this one finishes
            return
        self._start_cycle()

    def _start_cycle(self) -> None:
        pipeline, solution = self._get_pipeline(), self._get_solution()
        self.busy = True
        self._payload = None
        self.cycle_started.emit()
        self.state_changed.emit()

        def work():
            self._payload = self.compute_cycle(pipeline, solution)
            try:
                self._worker_done.emit()
            except RuntimeError:         # the engine was destroyed while the cycle was running
                pass

        self._thread = threading.Thread(target=work, name="flow-executor", daemon=True)
        self._thread.start()

    def _on_worker_done(self) -> None:
        payload, self._payload = self._payload, None
        if payload is None:              # already consumed by wait_for_run()
            return
        self.busy = False
        self._finish(payload)
        if self.pending:
            self.pending = False
            self.request_run()

    def wait_for_run(self) -> None:
        """Block until any in-flight cycle has ended and been shown (before the flow is edited)."""
        thread = self._thread
        if self.busy and thread is not None:
            thread.join()
            payload, self._payload = self._payload, None
            self.busy = False
            self.pending = False
            if payload is not None:
                self._finish(payload)
            else:
                self.state_changed.emit()

    def _finish(self, payload: dict) -> None:
        current = payload["pipeline"] is self._get_pipeline()
        if current:
            self.cycle_finished.emit(payload)
            self._after_cycle(self.payload_ok(payload))
        self.state_changed.emit()

    # ------------------------------------------------------------------ Run button
    def start_strip_run(self, scope: str, loop: bool) -> str:
        """The Run button: 'Run all' processes every image (repeating when ``loop``), 'Run
        selected' with Loop repeats the current one, anything else runs once.
        Returns ``"batch"`` or ``"single"``."""
        self.stopping = False
        self.strip_active = True
        n = len(self.pool)
        if scope == "Run all" and n > 0 and (loop or n > 1):
            self._start_batch(loop=loop)
            kind = "batch"
        elif loop and scope == "Run selected" and n > 0:
            self._start_batch(loop=True, only_current=True)
            kind = "batch"
        else:
            self.request_run()
            kind = "single"
        self.state_changed.emit()
        return kind

    def is_strip_busy(self) -> bool:
        return bool(self.strip_active or self.batch is not None or self._timer_active())

    def show_as_running(self) -> Tuple[bool, bool]:
        """``(running, stopping)`` for the Run / Stop button."""
        running = self.is_strip_busy() or (self.stopping and self.busy)
        return running, running and self.stopping

    def stop(self) -> None:
        self.batch = None
        self.strip_active = False
        self.stopping = self.busy
        self.state_changed.emit()

    # ------------------------------------------------------------------ continuous mode
    def reset_ticks(self) -> None:
        self.ticks = 0

    def auto_cycle(self, scope: str, loop: bool) -> bool:
        return loop and scope == "Run all" and len(self.pool) > 1

    def tick(self, scope: str, loop: bool) -> None:
        """One timer tick of continuous mode. With Loop + 'Run all' each tick takes the next
        image; a slow cycle just lowers the rate (ticks never queue)."""
        if self.busy:
            return
        if self.auto_cycle(scope, loop):
            if self.ticks > 0:
                self.select_image((self.pool.index + 1) % len(self.pool))
            self.ticks += 1
        self.request_run()

    # ------------------------------------------------------------------ images
    def select_image(self, row: int) -> None:
        """Feed pool image ``row`` to the active flow and tell the view to highlight it."""
        if self.pool.apply_to(self._get_pipeline(), row):
            self.image_selected.emit(row)

    # ------------------------------------------------------------------ batch / loop
    def _start_batch(self, loop: bool = False, only_current: bool = False) -> None:
        self.wait_for_run()
        indices = [self.pool.index] if only_current else list(range(len(self.pool)))
        self.batch = {"indices": indices, "queue": list(indices), "total": len(indices),
                      "done": 0, "ng": 0, "awaiting": False, "loop": loop, "pass": 1}
        self._batch_next()

    def _batch_next(self) -> None:
        batch = self.batch
        if batch is None or not batch["queue"]:
            return
        idx = batch["queue"].pop(0)
        self.select_image(idx)
        batch["awaiting"] = True
        position = batch["total"] - len(batch["queue"])
        prefix = f"Loop pass {batch['pass']}" if batch["loop"] else "Run all"
        self.progress.emit(f"{prefix}: image {position}/{batch['total']} - {self.pool.items[idx]['name']}")
        self.request_run()

    def _after_cycle(self, ok: bool) -> None:
        pipeline = self._get_pipeline()
        if not ok and getattr(pipeline, "stop_on_ng", False) and self.batch is not None:
            # "Stop on NG" halts Run all / Loop exactly as it halts continuous mode
            self.batch = None
            self.strip_active = False
            self.run_finished.emit("Stopped: NG detected (Stop on NG is active)")
        batch = self.batch
        if batch is not None and batch["awaiting"]:
            batch["awaiting"] = False
            batch["done"] += 1
            batch["ng"] += 0 if ok else 1
            if batch["queue"]:
                QTimer.singleShot(0, self._batch_next)
            elif batch["loop"]:
                batch["queue"] = list(batch["indices"])      # next pass, paced by the run interval
                batch["pass"] += 1
                QTimer.singleShot(max(0, int(self._interval_ms())), self._batch_next)
            else:
                self.batch = None
                self.strip_active = False
                self.run_finished.emit(f"Run all finished: {batch['done']} image(s), "
                                       f"{batch['ng']} NG, {batch['done'] - batch['ng']} OK")
        if self.batch is None and not self._timer_active():
            self.strip_active = False
            self.stopping = False


# =============================================================================
# Project state
# =============================================================================
class ProjectState:
    """Where the loaded solution came from and whether it has unsaved changes."""

    def __init__(self, project_manager) -> None:
        self.pm = project_manager
        self.path: Optional[str] = None
        self.saved: Optional[str] = None

    @staticmethod
    def snapshot(solution, before: Optional[Callable[[], None]] = None) -> Optional[str]:
        """Serialised solution minus transient counters (``None`` if it cannot be serialised)."""
        try:
            if before is not None:
                before()
            data = solution.to_dict()
            for flow in data.get("flows", []):
                flow.pop("execution_count", None)
            return json.dumps(data, sort_keys=True, default=str)
        except Exception:
            return None

    def mark_saved(self, solution, before: Optional[Callable[[], None]] = None) -> None:
        self.saved = self.snapshot(solution, before)

    def is_dirty(self, solution, before: Optional[Callable[[], None]] = None) -> bool:
        if self.saved is None:
            return False
        return self.snapshot(solution, before) != self.saved

    def save(self, solution, path: str, before: Optional[Callable[[], None]] = None) -> str:
        """Write the solution (format by extension) and remember it as the current file."""
        if before is not None:
            before()
        self.pm.save_project(solution, path)
        self.path = path
        self.mark_saved(solution, before)
        return path

    def open(self, path: str):
        """Load a solution file. Raises on corrupt files; the caller shows the message."""
        solution = self.pm.load_project(path)
        self.path = path
        return solution


# =============================================================================
# Flow editing operations (model side only - no view, no undo bookkeeping)
# =============================================================================
def make_module(pipeline, tool_name: str):
    """A new, unconnected module with a unique id and the next numbered display name."""
    from vm_clone.core.registry import create_tool_instance, new_instance_id
    index = len(pipeline.nodes) + 1
    return create_tool_instance(tool_name, new_instance_id("node"),
                                f"{index:02d}_{tool_name.replace(' ', '')}")


def auto_wire_image(pipeline, tool) -> Optional[str]:
    """Feed ``tool``'s Image input from the nearest upstream image producer.

    Returns the id of the module it was wired to, or ``None`` (no Image input / no producer).
    A newly inserted module is then immediately runnable."""
    if "Image" not in tool.inputs:
        return None
    for prev_id in reversed(pipeline.execution_order):
        if prev_id != tool.instance_id and prev_id in pipeline.nodes \
                and "Image" in pipeline.nodes[prev_id].outputs:
            if pipeline.connect(prev_id, "Image", tool.instance_id, "Image"):
                return prev_id
    return None


def add_module(pipeline, tool_name: str):
    """Create, add and auto-wire a module in one step."""
    tool = make_module(pipeline, tool_name)
    pipeline.add_node(tool)
    auto_wire_image(pipeline, tool)
    return tool


def connect_ports(pipeline, from_node: str, from_port: str, to_node: str, to_port: str) -> Tuple[bool, str]:
    """Wire two ports if the connection is legal. Returns ``(ok, reason_if_not)``."""
    ok, reason = pipeline.can_connect(from_node, from_port, to_node, to_port)
    if not ok:
        return False, reason
    return pipeline.connect(from_node, from_port, to_node, to_port), ""
