"""Python backend for the QML user interface (``qml/``).

The QML screens are pure presentation; this object feeds them the real solution (flows,
wiring, layout, results, the current image) and executes their commands.  It is exposed to
QML as the context property ``appBackend`` - when it is absent (Qt Design Studio) the
screens fall back to ``ApexTheme/SampleData.qml``.

Everything here is Qt-widget free, so it works with ``QGuiApplication`` only.
"""
import json
import os
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage
from PyQt6.QtQuick import QQuickImageProvider

import apex_vision.tools  # noqa: F401  (registers the tools)
from apex_vision.core.base_tool import DataType, ToolStatus
from apex_vision.core.formatting import format_flow_outputs
from apex_vision.core.overlays import DEFAULT_LAYERS, render_overlays
from apex_vision.core.controller import (ImagePool, ProjectState, RunEngine, add_module,
                                      connect_ports)
from apex_vision.core.pipeline import SolutionManager
from apex_vision.core.project_manager import ProjectManager
from apex_vision.version import DISPLAY as APP_VERSION
from apex_vision.core.registry import create_tool_instance, new_instance_id

ROLES = ["Administrator", "Engineer", "Operator"]
TEMPLATE_KEYS = ["blank", "pcb", "measurement", "yolo", "calibration"]
_PORT_KIND = {DataType.IMAGE: "image", DataType.VALUE: "value", DataType.BOOLEAN: "value",
              DataType.STRING: "string"}


class FrameProvider(QQuickImageProvider):
    """``image://frame/<token>`` - serves the image the backend last produced."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.image = QImage()

    def requestImage(self, image_id, requested_size):  # noqa: N802
        if self.image.isNull():
            blank = QImage(1, 1, QImage.Format.Format_ARGB32)
            blank.fill(0)
            return blank, blank.size()
        return self.image, self.image.size()

    def set_array(self, arr: Optional[np.ndarray]) -> None:
        if arr is None:
            self.image = QImage()
            return
        arr = np.ascontiguousarray(arr)
        if arr.ndim == 2:
            h, w = arr.shape
            self.image = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
        else:
            h, w = arr.shape[:2]
            rgb = np.ascontiguousarray(arr[:, :, 2::-1]) if arr.shape[2] >= 3 else arr
            self.image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class AppBackend(QObject):
    changed = pyqtSignal()
    startPageRequested = pyqtSignal()
    workspaceRequested = pyqtSignal()
    closeApproved = pyqtSignal()            # the window may close (nothing unsaved, or the user decided)
    confirmRequested = pyqtSignal(str)      # unsaved edits would be lost - ask the user first

    def __init__(self, provider: FrameProvider, project_manager: Optional[ProjectManager] = None):
        super().__init__()
        self._provider = provider
        self._pm = project_manager or ProjectManager()
        self._solution = SolutionManager(name="Untitled")
        self._project = ProjectState(self._pm)
        self._role = "Engineer"
        self._hint = "Ready"
        self._selected = ""
        self._token = 0
        self._verdict = "PASS"
        self._flow_ms = 0.0
        self._algo_ms = 0.0
        self._results: List[Dict[str, str]] = []
        self._scope = "Run all"
        self._loop = False
        self._undo: List[str] = []
        self._redo: List[str] = []
        self._cameras: List[Dict[str, str]] = []
        self._pending = None                      # action waiting for the unsaved-changes answer
        self._last_image = None
        self._last_results: Dict[str, Any] = {}
        self._layers: Dict[str, bool] = dict(DEFAULT_LAYERS)
        self._formatted = ""
        # run / loop / stop / image pool are the shared controller - the same code the widget UI uses
        self._pool = ImagePool()
        self.engine = RunEngine(get_pipeline=lambda: self._pipeline, get_solution=lambda: self._solution,
                                pool=self._pool, interval_ms=lambda: int(self._pipeline.run_interval_ms),
                                parent=self)
        self.engine.cycle_finished.connect(self._on_cycle)
        self.engine.state_changed.connect(lambda: self.changed.emit())
        self.engine.image_selected.connect(lambda _row: self.changed.emit())
        self.engine.progress.connect(lambda text: self._notify(text))
        self.engine.run_finished.connect(lambda text: self._notify(text))

    # ------------------------------------------------------------------ helpers
    @property
    def _pipeline(self):
        return self._solution.get_active_flow()

    def _snapshot(self) -> str:
        return ProjectState.snapshot(self._solution) or ""

    def _notify(self, hint: Optional[str] = None) -> None:
        if hint is not None:
            self._hint = hint
        self.changed.emit()

    def _push_undo(self) -> None:
        self._undo.append(self._snapshot())
        del self._undo[:-50]
        self._redo.clear()

    def _restore(self, snapshot: str) -> None:
        self._solution = SolutionManager.from_dict(json.loads(snapshot))
        self._freeze_layout()
        if self._selected not in self._pipeline.nodes:
            self._selected = next(iter(self._pipeline.execution_order), "")

    # ------------------------------------------------------------------ properties
    @pyqtProperty(str, notify=changed)
    def solutionName(self):  # noqa: N802
        return self._solution.name

    @pyqtProperty(bool, notify=changed)
    def dirty(self):
        return self._project.is_dirty(self._solution)

    @pyqtProperty(str, notify=changed)
    def role(self):
        return self._role

    @pyqtProperty(str, notify=changed)
    def hint(self):
        return self._hint

    @pyqtProperty(bool, notify=changed)
    def running(self):
        return self.engine.show_as_running()[0]

    @pyqtProperty(str, notify=changed)
    def verdict(self):
        return self._verdict

    @pyqtProperty(float, notify=changed)
    def flowMs(self):  # noqa: N802
        return self._flow_ms

    @pyqtProperty(float, notify=changed)
    def algoMs(self):  # noqa: N802
        return self._algo_ms

    @pyqtProperty(str, notify=changed)
    def imageUrl(self):  # noqa: N802
        return f"image://frame/{self._token}"

    @pyqtProperty("QVariantMap", notify=changed)
    def layers(self):
        return dict(self._layers)

    @pyqtSlot(str, bool)
    def setLayer(self, name, on):  # noqa: N802
        if name in self._layers:
            self._layers[name] = bool(on)
            if name == "overlays":
                for key in ("rois", "metrics", "datums"):
                    self._layers[key] = bool(on)
            self._render_view()
            self.changed.emit()

    @pyqtProperty(str, notify=changed)
    def formattedOutput(self):  # noqa: N802
        return self._formatted

    def _view_image_and_overlays(self):
        """The selected module's output image with its overlays (else the flow's last image)."""
        pipe = self._pipeline
        res = self._last_results.get(self._selected)
        if res is not None and res.outputs.get("Image") is not None:
            return res.outputs["Image"], res.overlays
        node = pipe.nodes.get(self._selected)
        if node is not None:                      # modules without an image output show their input
            for c in pipe.connections:
                if c.to_node == self._selected and c.to_port == "Image":
                    upstream = self._last_results.get(c.from_node)
                    if upstream is not None and upstream.outputs.get(c.from_port) is not None:
                        return upstream.outputs[c.from_port], (res.overlays if res else [])
        overlays = [o for r in self._last_results.values() for o in r.overlays]
        return self._last_image, overlays

    def _render_view(self) -> None:
        image, overlays = self._view_image_and_overlays()
        self._provider.set_array(render_overlays(image, overlays, self._layers))
        self._token += 1

    @pyqtProperty(str, constant=True)
    def version(self):
        return APP_VERSION

    @pyqtProperty("QVariantList", notify=changed)
    def results(self):
        return self._results

    @pyqtProperty("QVariantList", notify=changed)
    def recentProjects(self):  # noqa: N802
        return [{"name": r.get("name", ""), "path": r.get("path", ""),
                 "when": str(r.get("last_opened", ""))}
                for r in self._pm.get_recent_projects() if r.get("file_exists", True)]

    @pyqtProperty("QVariantList", notify=changed)
    def imagePool(self):  # noqa: N802
        return [{"name": i["name"], "url": QUrl.fromLocalFile(i["path"]).toString() if i.get("path") else ""}
                for i in self._pool.items]

    @pyqtProperty(int, notify=changed)
    def imageIndex(self):  # noqa: N802
        return self._pool.index

    def _get_loop(self) -> bool:
        return self._loop

    def _set_loop(self, value: bool) -> None:
        self._loop = bool(value)
        self.changed.emit()

    loop = pyqtProperty(bool, _get_loop, _set_loop, notify=changed)

    @pyqtProperty("QVariantList", notify=changed)
    def globalVariables(self):  # noqa: N802
        return [{"name": k, "type": type(v).__name__, "value": str(v)}
                for k, v in self._solution.global_variables.items()]

    @pyqtProperty("QVariantMap", notify=changed)
    def flowSettings(self):  # noqa: N802
        p = self._pipeline
        return {"runIntervalMs": p.run_interval_ms, "timeoutMs": p.flow_timeout_ms,
                "stopOnNg": p.stop_on_ng, "enabled": p.enabled}

    @pyqtProperty("QVariantList", notify=changed)
    def cameras(self):
        return self._cameras

    @pyqtProperty("QVariantList", notify=changed)
    def toolCategories(self):  # noqa: N802
        """Tool box content from the live registry, so plugin tools show up too."""
        from apex_vision.core.registry import list_categories
        icons = {"Acquisition": "camera", "Location": "target", "Measurement": "measure",
                 "Image Generation": "roi", "Image Processing": "grid", "Recognition": "text",
                 "Defect Detection": "shield", "Color Processing": "palette", "Calibration": "grid",
                 "Communication": "comm", "Logic Tools": "logic"}
        return [{"name": name, "icon": icons.get(name, "list"), "tools": list(tools)}
                for name, tools in list_categories().items()]

    # ------------------------------------------------------------------ hooks for the services
    def currentFlowImage(self):  # noqa: N802
        """The most recent image the active flow produced (or None)."""
        return self._last_image

    def editWith(self, edit, message: str) -> None:  # noqa: N802
        """Run ``edit(pipeline)`` as one undoable change, then re-run the flow."""
        if not self._editable():
            return
        self._push_undo()
        edit(self._pipeline)
        self._freeze_layout()
        self._notify(message)
        self._rerun()

    def activePipeline(self):  # noqa: N802
        return self._pipeline

    def toolsChanged(self) -> None:  # noqa: N802
        self.changed.emit()

    def notify(self, text: str) -> None:
        self._notify(text)

    def projectsDirectory(self) -> str:  # noqa: N802
        return self._pm.default_projects_dir

    _ROI_KEYS = ("roi", "template_roi")

    def _roi_key(self):
        node = self._pipeline.nodes.get(self._selected)
        if node is None:
            return None, None
        for key in self._ROI_KEYS:
            value = node.parameters.get(key)
            if isinstance(value, (list, tuple)) and len(value) == 4:
                return node, key
        return node, None

    @pyqtProperty(str, notify=changed)
    def selectedId(self):  # noqa: N802
        return self._selected

    @pyqtProperty("QVariantList", notify=changed)
    def selectedRoi(self):  # noqa: N802
        """[x, y, w, h] in image pixels of the selected module's ROI, or [] if it has none."""
        node, key = self._roi_key()
        return [int(v) for v in node.parameters[key]] if key else []

    @pyqtSlot(int, int, result=str)
    def pixelInfo(self, x, y):  # noqa: N802
        """``R:12 G:34 B:56`` of the displayed image at (x, y); dashes outside the image."""
        img = self._provider.image
        if img.isNull() or not (0 <= x < img.width() and 0 <= y < img.height()):
            return "R:--- G:--- B:---"
        c = img.pixelColor(x, y)
        return f"R:{c.red()} G:{c.green()} B:{c.blue()}"

    @pyqtSlot(int, int, int, int)
    def setRoi(self, x, y, w, h):  # noqa: N802
        node, key = self._roi_key()
        if key is None or not self._editable():
            return
        self._push_undo()
        node.set_param(key, [int(x), int(y), max(1, int(w)), max(1, int(h))])
        self._notify(f"ROI set to {x}, {y}, {w}, {h}")
        self._rerun()

    @pyqtProperty("QVariantList", notify=changed)
    def nodes(self):
        pipe = self._pipeline
        positions = self._positions(pipe)
        out = []
        for nid in pipe.execution_order:
            node = pipe.nodes[nid]
            res = pipe.last_results.get(nid)
            status = "FAIL" if (res is not None and res.status in (ToolStatus.NG, ToolStatus.ERROR)) else "PASS"
            x, y = positions.get(nid, (50.0, 50.0))
            out.append({
                "id": nid,
                "title": node.name.replace("_", " ", 1),
                "tool": node.tool_name,                # the toolbox entry this module is an instance of
                "status": status,
                "ms": float(res.elapsed_ms) if res is not None else 0.0,
                "x": x, "y": y,
                "inputs": [{"name": n, "type": _PORT_KIND.get(p.data_type, "region"), "dtype": p.data_type.name}
                           for n, p in node.inputs.items()],
                "outputs": [{"name": n, "type": _PORT_KIND.get(p.data_type, "region"), "dtype": p.data_type.name}
                            for n, p in node.outputs.items()],
            })
        return out

    @pyqtProperty("QVariantList", notify=changed)
    def connections(self):
        pipe = self._pipeline
        out = []
        for c in pipe.connections:
            src, dst = pipe.nodes.get(c.from_node), pipe.nodes.get(c.to_node)
            if src is None or dst is None:
                continue
            try:
                out.append({"from": c.from_node, "fromPort": list(src.outputs).index(c.from_port),
                            "to": c.to_node, "toPort": list(dst.inputs).index(c.to_port)})
            except ValueError:
                continue
        return out

    # ------------------------------------------------------------------ layout
    def _freeze_layout(self, pipe=None) -> None:
        """Store the computed auto-layout as real positions, so later wiring changes never reshuffle."""
        pipe = pipe or self._pipeline
        if not all(n in pipe.node_positions for n in pipe.nodes):
            computed = self._positions(pipe)
            for nid in pipe.nodes:
                pipe.node_positions.setdefault(nid, list(computed[nid]))

    def _positions(self, pipe) -> Dict[str, tuple]:
        if pipe.node_positions and all(n in pipe.node_positions for n in pipe.nodes):
            return {k: (float(v[0]), float(v[1])) for k, v in pipe.node_positions.items()}
        levels: Dict[str, int] = {}
        for nid in pipe.execution_order:
            preds = [c.from_node for c in pipe.connections if c.to_node == nid]
            levels[nid] = 0 if not preds else max(levels.get(p, 0) for p in preds) + 1
        rows: Dict[int, int] = {}
        out = {}
        for nid in pipe.execution_order:
            lvl = levels[nid]
            r = rows.get(lvl, 0)
            rows[lvl] = r + 1
            out[nid] = (50.0 + lvl * 260.0, 50.0 + r * 175.0)
        return out

    # ------------------------------------------------------------------ solution
    def load_solution(self, solution: SolutionManager, path: Optional[str] = None) -> None:
        self._solution = solution
        self._project.path = path
        self._selected = next(iter(self._pipeline.execution_order), "")
        self._results = []
        self._undo.clear()
        self._redo.clear()
        self._freeze_layout()
        self._seed_sample_images()
        self._project.mark_saved(solution)
        self._notify(f"Loaded solution '{solution.name}' ({len(solution.flows)} flow(s))")
        self.workspaceRequested.emit()
        self._rerun()

    def _guard(self, action) -> None:
        """Run ``action`` now, or after the user decided what to do with unsaved edits."""
        if self.dirty:
            self._pending = action
            self.confirmRequested.emit(f"'{self._solution.name}' has unsaved changes. "
                                       "Save them before continuing?")
            return
        action()

    @pyqtSlot()
    def confirmSave(self):  # noqa: N802
        action, self._pending = self._pending, None
        if action is None:
            return
        if not self._project.path:
            self._notify("This solution has no file yet - use Save Solution As first")
            return
        self.saveProject()
        if not self.dirty:
            action()

    @pyqtSlot()
    def confirmDiscard(self):  # noqa: N802
        action, self._pending = self._pending, None
        if action is not None:
            action()

    @pyqtSlot()
    def confirmCancel(self):  # noqa: N802
        self._pending = None
        self._notify("Cancelled")

    @pyqtProperty(bool, notify=changed)
    def showStartPageOnStartup(self):  # noqa: N802
        return bool(self._pm.get_show_on_startup())

    @pyqtSlot(bool)
    def setShowStartPageOnStartup(self, value):  # noqa: N802
        self._pm.set_show_on_startup(bool(value))
        self.changed.emit()

    def startup(self, path: Optional[str] = None) -> None:
        """What the widget app does at launch: open the file given, else show the start page
        (when enabled), over the default sample solution so the workspace is never empty."""
        if path:
            self.openRecent(path)
            return
        from apex_vision.samples.pcb_solution import create_pcb_inspection_solution
        sol = SolutionManager(name="IndustrialSolution")
        sol.flows["Flow1"] = create_pcb_inspection_solution()
        sol.active_flow_name = "Flow1"
        self.load_solution(sol, None)
        if self._pm.get_show_on_startup():
            self.startPageRequested.emit()

    @pyqtSlot()
    def requestClose(self):  # noqa: N802
        """The window asked to close: ask about unsaved edits first."""
        self._guard(self.closeApproved.emit)

    def _seed_sample_images(self) -> None:
        """Like the widget app, start with the two bundled sample boards in the image strip.

        They are only listed - the Image Source keeps its own input until one is selected."""
        if len(self._pool):
            return
        samples = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
        for name in ("pcb_sample.png", "pcb_sample_defect.png"):
            self._pool.add_path(os.path.join(samples, name))
        self._pool.index = 0

    @pyqtSlot(str)
    def openRecent(self, path):  # noqa: N802
        def do():
            try:
                self.load_solution(self._project.open(path), path)
            except Exception as exc:
                self._notify(f"Could not open {os.path.basename(path)}: {exc}")
        self._guard(do)

    @pyqtSlot(str, result=str)
    def urlToPath(self, url):  # noqa: N802
        """``file:///C:/x/y.vmp`` -> ``C:/x/y.vmp`` (QML dialogs return URLs)."""
        return QUrl(url).toLocalFile() or url

    @pyqtProperty(str, notify=changed)
    def flowName(self):  # noqa: N802
        return self._solution.active_flow_name

    @pyqtSlot(str)
    def exportResultsCsv(self, url):  # noqa: N802
        """Per-module verdicts of the last run, one row per module."""
        import csv
        path = self.urlToPath(url)
        pipe = self._pipeline
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Module", "Kernel", "Status", "Latency_ms", "Message"])
                for nid in pipe.execution_order:
                    res, node = pipe.last_results.get(nid), pipe.nodes.get(nid)
                    if res and node:
                        w.writerow([node.name, node.tool_name, res.status.value.upper(), f"{res.elapsed_ms:.2f}", res.message])
            self._notify(f"Saved results to {path}")
        except Exception as exc:
            self._notify(f"Export failed: {exc}")

    @pyqtSlot(str)
    def exportFlowXml(self, url):  # noqa: N802
        path = self.urlToPath(url)
        try:
            self._freeze_layout()
            self._solution.export_flow_xml(self._solution.active_flow_name, path)
            self._notify(f"Flow exported to {path}")
        except Exception as exc:
            self._notify(f"Export failed: {exc}")

    @pyqtSlot(str)
    def importFlowXml(self, url):  # noqa: N802
        if not self._editable():
            return
        path = self.urlToPath(url)
        self._push_undo()
        try:
            flow = self._solution.import_flow_xml(path)
        except Exception as exc:
            self._undo.pop()
            self._notify(f"Import failed: {exc}")
            return
        self._solution.active_flow_name = flow.name
        self._freeze_layout()
        self._notify(f"Imported flow {flow.name}")
        self._rerun()

    @pyqtSlot(result=str)
    def moduleLog(self):  # noqa: N802
        """Plain-text trace of the last run (what the Log Viewer shows)."""
        pipe = self._pipeline
        lines = []
        for nid in pipe.execution_order:
            res, node = pipe.last_results.get(nid), pipe.nodes.get(nid)
            if res and node:
                lines.append(f"{node.name:<28} {res.status.value.upper():<6} {res.elapsed_ms:7.1f} ms  {res.message}")
        return chr(10).join(lines) or "No run yet - press Run to produce a module log."

    @pyqtSlot()
    def saveProject(self):  # noqa: N802
        if not self._project.path:
            self._notify("Choose File > Save Solution As... to pick a file first")
            return
        self.saveProjectAs(self._project.path)

    @pyqtSlot(str)
    def saveProjectAs(self, path):  # noqa: N802
        if not os.path.splitext(path)[1]:
            path += ".vmp"
        try:
            self._project.save(self._solution, path)
        except Exception as exc:
            self._notify(f"Save failed: {exc}")
            return
        self._notify(f"Saved to {path}")

    @pyqtSlot(int)
    def newFromTemplate(self, index):  # noqa: N802
        template = ["pcb", "measurement", "yolo", "calibration"][max(0, min(index, 3))]

        def do():
            sol, path = self._pm.create_project(f"Solution_{template.upper()}", template=template)
            self.load_solution(sol, path)
        self._guard(do)

    @pyqtSlot(str, str, int)
    def createProject(self, name, folder, template):  # noqa: N802
        def do():
            sol, path = self._pm.create_project(name, folder, template=TEMPLATE_KEYS[max(0, min(template, 4))])
            self.load_solution(sol, path)
        self._guard(do)

    @pyqtSlot(str)
    def removeRecent(self, path):  # noqa: N802
        self._pm.remove_recent_project(path)
        self._notify()

    @pyqtSlot()
    def showStartPage(self):  # noqa: N802
        self.startPageRequested.emit()

    @pyqtSlot(str)
    def setRole(self, role):  # noqa: N802
        if role in ROLES:
            self._role = role
            self._notify(f"Role: {role}" + (" - editing locked" if role == "Operator" else ""))

    @pyqtSlot()
    def cycleRole(self):  # noqa: N802
        self._role = ROLES[(ROLES.index(self._role) + 1) % len(ROLES)]
        self._notify(f"Role: {self._role}" + (" - editing locked" if self._role == "Operator" else ""))

    # ------------------------------------------------------------------ editing
    def _editable(self) -> bool:
        if self._role == "Operator":
            self._notify("Editing is locked for the Operator role")
            return False
        return True

    @pyqtSlot(str)
    def selectNode(self, node_id):  # noqa: N802
        self._selected = node_id
        self._render_view()
        self._refresh_results()
        self._notify()

    @pyqtSlot()
    def beginMove(self):  # noqa: N802
        """A module drag started: one undo step covers the whole drag."""
        if self._editable():
            self._freeze_layout()
            self._push_undo()

    @pyqtSlot(str, float, float)
    def moveNode(self, node_id, x, y):  # noqa: N802
        pipe = self._pipeline
        if node_id in pipe.nodes and self._editable():
            for nid, (px, py) in self._positions(pipe).items():
                pipe.node_positions.setdefault(nid, [px, py])
            pipe.node_positions[node_id] = [float(x), float(y)]

    @pyqtSlot(str)
    def addTool(self, tool_name):  # noqa: N802
        if not self._editable():
            return
        self._push_undo()
        pipe = self._pipeline
        existing = self._positions(pipe)
        tool = add_module(pipe, tool_name)           # shared with the widget UI: numbering + auto-wiring
        lowest = max(existing.values(), key=lambda p: p[1], default=(50.0, -100.0))
        pipe.node_positions = {k: list(v) for k, v in existing.items()}
        pipe.node_positions[tool.instance_id] = [lowest[0], lowest[1] + 175.0]
        self._selected = tool.instance_id
        self._notify(f"Inserted module: {tool_name}")
        self._rerun()

    @pyqtSlot(str, int, str, int, result=str)
    def canConnect(self, from_id, from_index, to_id, to_index):  # noqa: N802
        """'' when the wire is allowed, else the reason (type mismatch, loop, same module ...)."""
        pipe = self._pipeline
        src, dst = pipe.nodes.get(from_id), pipe.nodes.get(to_id)
        if src is None or dst is None:
            return "That module no longer exists."
        if from_id == to_id:
            return "Cannot connect a module to itself."
        try:
            from_port, to_port = list(src.outputs)[from_index], list(dst.inputs)[to_index]
        except IndexError:
            return "That port does not exist."
        ok, reason = pipe.can_connect(from_id, from_port, to_id, to_port)
        return "" if ok else reason

    @pyqtSlot(str, int, str, int, str, int, result=bool)
    def reconnect(self, from_id, from_index, old_to_id, old_to_index, new_to_id, new_to_index):  # noqa: N802
        """Move the end of a wire to another input (or drop it when ``new_to_id`` is empty) as ONE undo step."""
        pipe = self._pipeline
        src, old = pipe.nodes.get(from_id), pipe.nodes.get(old_to_id)
        if src is None or old is None or not self._editable():
            return False
        try:
            old_port = list(old.inputs)[old_to_index]
        except IndexError:
            return False
        if new_to_id == "":
            self._push_undo()
            pipe.disconnect(old_to_id, old_port)
            self._notify(f"Disconnected {old.name}.{old_port}")
            self._rerun()
            return True
        if new_to_id == old_to_id and new_to_index == old_to_index:
            return True
        reason = self.canConnect(from_id, from_index, new_to_id, new_to_index)
        if reason:
            self._notify(reason)
            return False
        self._push_undo()
        pipe.disconnect(old_to_id, old_port)
        dst = pipe.nodes[new_to_id]
        ok, why = connect_ports(pipe, from_id, list(src.outputs)[from_index], new_to_id, list(dst.inputs)[new_to_index])
        if not ok:
            self._undo.pop()
            self._notify(why or "Connection rejected")
            return False
        self._notify(f"Moved the wire to {dst.name}.{list(dst.inputs)[new_to_index]}")
        self._rerun()
        return True

    @pyqtSlot(str, int, str, int, result=bool)
    def connectPorts(self, from_id, from_index, to_id, to_index):  # noqa: N802
        """Wire output #from_index of one module to input #to_index of another."""
        pipe = self._pipeline
        src, dst = pipe.nodes.get(from_id), pipe.nodes.get(to_id)
        if src is None or dst is None or not self._editable():
            return False
        try:
            from_port, to_port = list(src.outputs)[from_index], list(dst.inputs)[to_index]
        except IndexError:
            return False
        self._push_undo()
        ok, reason = connect_ports(pipe, from_id, from_port, to_id, to_port)
        if not ok:
            self._undo.pop()
            self._notify(reason or "Connection rejected")
            return False
        self._notify(f"Connected {src.name}.{from_port} -> {dst.name}.{to_port}")
        self._rerun()
        return True

    @pyqtSlot(str, int)
    def disconnectInput(self, to_id, to_index):  # noqa: N802
        pipe = self._pipeline
        dst = pipe.nodes.get(to_id)
        if dst is None or not self._editable():
            return
        try:
            port = list(dst.inputs)[to_index]
        except IndexError:
            return
        self._push_undo()
        pipe.disconnect(to_id, port)
        self._notify(f"Disconnected {dst.name}.{port}")
        self._rerun()

    @pyqtSlot(str)
    def deleteNode(self, node_id):  # noqa: N802
        pipe = self._pipeline
        node = pipe.nodes.get(node_id)
        if node is None or not self._editable():
            return
        self._push_undo()
        pipe.remove_node(node_id)
        if self._selected == node_id:
            self._selected = next(iter(pipe.execution_order), "")
        self._notify(f"Deleted {node.name}")
        self._rerun()

    @pyqtSlot()
    def arrange(self):
        self._push_undo()
        self._pipeline.node_positions = {}
        self._freeze_layout()
        self._notify("Modules arranged")

    @pyqtSlot()
    def addFlow(self):  # noqa: N802
        self._push_undo()
        n = len(self._solution.flows) + 1
        while f"Flow{n}" in self._solution.flows:
            n += 1
        flow = self._solution.add_flow(f"Flow{n}")
        flow.add_node(create_tool_instance("Image Source", new_instance_id("src"), "01_Acquisition"))
        self._solution.active_flow_name = flow.name
        self._freeze_layout()
        self._notify(f"Created sub-flow {flow.name}")
        self._rerun()

    @pyqtSlot(str, str, result=bool)
    def applyGeneratedFlow(self, spec_json, mode):  # noqa: N802
        """Add a flow built by the AI assistant: as a new flow (``new``) or in place of the open one (``replace``)."""
        from apex_vision.flowgen.spec import build_flow
        if not self._editable():
            return False
        try:
            pipe, issues = build_flow(json.loads(spec_json))
        except ValueError as exc:
            self._notify(f"Could not read the generated flow: {exc}")
            return False
        if pipe is None:
            self._notify("The generated flow has errors and was not added")
            return False
        self._push_undo()
        if mode == "replace":
            name = self._solution.active_flow_name          # keeps its place and name (and trigger status)
        else:
            name, n = pipe.name, 1
            while name in self._solution.flows:
                n += 1
                name = f"{pipe.name}_{n}"
        pipe.name = name
        self._solution.flows[name] = pipe
        self._solution.active_flow_name = name
        self._selected = next(iter(pipe.execution_order), "")
        self._freeze_layout()
        self._notify(f"Added AI-generated flow {name} ({len(pipe.nodes)} modules)")
        self.workspaceRequested.emit()
        self._rerun()
        return True

    @pyqtSlot()
    def undo(self):
        if not self._undo:
            self._notify("Nothing to undo")
            return
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self._notify("Undo")

    @pyqtSlot()
    def redo(self):
        if not self._redo:
            self._notify("Nothing to redo")
            return
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        self._notify("Redo")

    @pyqtSlot(str, str, str)
    def setGlobal(self, name, kind, text):  # noqa: N802
        name = name.strip()
        if not name or not self._editable():
            return
        converters = {"Integer": int, "Float": float,
                      "Boolean": lambda t: t.strip().lower() in ("1", "true", "yes")}
        try:
            value: Any = converters.get(kind, str)(text)
        except ValueError:
            self._notify(f"'{text}' is not a valid {kind.lower()}")
            return
        self._push_undo()
        self._solution.global_variables[name] = value
        self._notify(f"Variable {name} = {value}")

    @pyqtSlot(str)
    def removeGlobal(self, name):  # noqa: N802
        if name in self._solution.global_variables and self._editable():
            self._push_undo()
            del self._solution.global_variables[name]
            self._notify(f"Removed {name}")

    @pyqtSlot(float, float, bool, bool)
    def applyFlowSettings(self, interval, timeout, stop_on_ng, enabled):  # noqa: N802
        if not self._editable():
            return
        self._push_undo()
        p = self._pipeline
        p.run_interval_ms, p.flow_timeout_ms = max(10.0, interval), max(100.0, timeout)
        p.stop_on_ng, p.enabled = bool(stop_on_ng), bool(enabled)
        self._notify("Flow settings updated")

    @pyqtSlot(str, result="QVariantList")
    def moduleInputs(self, node_id):  # noqa: N802
        pipe = self._pipeline
        node = pipe.nodes.get(node_id)
        if node is None:
            return []
        out = []
        for port, p in node.inputs.items():
            src = next((c for c in pipe.connections if c.to_node == node_id and c.to_port == port), None)
            label = ""
            if src is not None and src.from_node in pipe.nodes:
                label = f"{pipe.nodes[src.from_node].name} [{src.from_port}]"
            out.append({"name": port, "type": p.data_type.value, "source": label or "(not connected)"})
        return out

    @pyqtSlot(str, str, result=str)
    def renameNode(self, node_id, new_name):  # noqa: N802
        """Rename a module (its label only; the tool it is an instance of is unchanged).  Returns '' on success, else
        what is wrong with the name.  One undo step."""
        node = self._pipeline.nodes.get(node_id)
        if node is None:
            return "That module no longer exists."
        name = " ".join(new_name.split())
        if not name:
            return "Enter a name."
        if len(name) > 48:
            return "Use at most 48 characters."
        if any(ord(c) < 32 for c in new_name):
            return "The name cannot contain control characters."
        if "," in name:
            return "The name cannot contain commas (results are exported as comma-separated text)."
        shown = lambda n: n.replace("_", " ", 1)
        if name == shown(node.name) or name == node.name:
            return ""
        if any(o.name == name or shown(o.name) == name for k, o in self._pipeline.nodes.items() if k != node_id):
            return f"Another module in this flow is already called '{name}'."
        if not self._editable():
            return "Editing is locked for the Operator role."
        self._push_undo()
        old = node.name
        node.name = name
        self._notify(f"Renamed {shown(old)} to {name}")
        return ""

    @pyqtSlot(str, result=str)
    def toolOf(self, node_id):  # noqa: N802
        node = self._pipeline.nodes.get(node_id)
        return node.tool_name if node else ""

    @pyqtSlot(str, result="QVariantList")
    def moduleParams(self, node_id):  # noqa: N802
        """Every parameter of a module with how to edit it (kind, choices, limits, unit) - see ``param_schema``."""
        from apex_vision.core import param_schema
        node = self._pipeline.nodes.get(node_id)
        if node is None:
            return []
        out = []
        for k, v in node.parameters.items():
            spec = param_schema.spec_for(node.tool_name, k, v)
            if spec["kind"] == "flow":
                spec["choices"] = list(self._solution.flows)
            elif spec["kind"] == "device":
                spec["choices"] = self._camera_ids(v)
            spec.update({"name": k, "type": type(v).__name__, "native": v,
                         "value": json.dumps(v) if isinstance(v, (list, dict)) else str(v)})
            out.append(spec)
        return out

    def _camera_ids(self, current: Any) -> List[str]:
        ids = []
        try:
            from apex_vision.core.camera_manager import CameraManager
            ids = [d.device_id for d in CameraManager.get_instance().list_devices()]
        except Exception:
            pass
        if current and current not in ids:
            ids.insert(0, str(current))
        return ids

    @pyqtSlot(str, str, "QVariant", result=bool)
    def setParamValue(self, node_id, key, value):  # noqa: N802
        """Set a parameter from an editor.  Numbers are brought into range; anything the parameter cannot hold is
        refused with a message.  One undo step per change, and the flow re-runs."""
        from apex_vision.core import param_schema
        node = self._pipeline.nodes.get(node_id)
        if node is None or key not in node.parameters or not self._editable():
            return False
        if hasattr(value, "toVariant"):                       # a JS array / object arrives as QJSValue
            value = value.toVariant()
        old = node.parameters[key]
        spec = param_schema.spec_for(node.tool_name, key, old)
        value = param_schema.clamp(spec, value)
        if isinstance(value, float) and spec["kind"] == "float":
            value = round(value, 6)
        issue = param_schema.problem(node.tool_name, key, old, value)
        if issue:
            self._notify(f"{spec['label']} {issue}")
            return False
        if value == old:
            return True
        self._push_undo()
        node.set_param(key, value)
        if node.parameters[key] != value:                      # the tool's own type check refused it
            self._undo.pop()
            self._notify(f"{spec['label']}: the module did not accept that value")
            return False
        self._notify(f"{node.name}: {spec['label']} set to {value if not isinstance(value, list) else json.dumps(value)}")
        self._rerun()
        return True

    @pyqtSlot(str, str, str)
    def setParam(self, node_id, key, text):  # noqa: N802
        """Text form of ``setParamValue`` (scripts, older callers): the text is read as the parameter's own type."""
        node = self._pipeline.nodes.get(node_id)
        if node is None or key not in node.parameters:
            return
        old = node.parameters[key]
        try:
            if isinstance(old, bool):
                value: Any = text.strip().lower() in ("1", "true", "yes")
            elif isinstance(old, int):
                value = int(float(text))
            elif isinstance(old, float):
                value = float(text)
            elif isinstance(old, (list, dict)):
                value = json.loads(text)
            else:
                value = text
        except (ValueError, json.JSONDecodeError):
            return
        self.setParamValue(node_id, key, value)

    @pyqtSlot(result="QVariantList")
    def validateFlow(self):  # noqa: N802
        pipe = self._pipeline
        issues = []
        for issue in pipe.validate_flow():
            node = pipe.nodes.get(issue.get("node_id", ""))
            issues.append({"severity": str(issue.get("severity", "info")),
                           "node": node.name if node else str(issue.get("node_id", "Flow")),
                           "message": str(issue.get("message", ""))})
        if not issues:
            issues.append({"severity": "info", "node": "Flow",
                           "message": f"{len(pipe.nodes)} modules, {len(pipe.connections)} connections, no problems."})
        return issues

    @pyqtSlot()
    def refreshCameras(self):  # noqa: N802
        try:
            from apex_vision.core.camera_manager import CameraManager
            self._cameras = [{"name": d.name, "type": d.camera_type, "serial": d.serial_number,
                              "iface": d.interface_name} for d in CameraManager.get_instance().list_devices()]
        except Exception as exc:
            self._cameras = []
            self._hint = f"Camera scan failed: {exc}"
        self.changed.emit()

    # ------------------------------------------------------------------ images
    def _ensure_pool_applied(self) -> None:
        self._pool.apply_to(self._pipeline)

    @pyqtSlot("QVariantList")
    def loadImageFiles(self, urls):  # noqa: N802
        added, first = 0, None
        for u in urls:
            idx, _err = self._pool.add_path(self.urlToPath(str(u)))
            if idx is not None:
                added += 1
                first = idx if first is None else first
        if first is not None:
            self._pool.select(first)
            self._ensure_pool_applied()
        self._notify(f"Loaded {added} image(s)")
        if added:
            self._rerun()

    @pyqtSlot(str)
    def loadImageFolder(self, url):  # noqa: N802
        folder = self.urlToPath(url)
        try:
            added, skipped, failed = self._pool.add_folder(folder)
        except OSError as exc:
            self._notify(f"Cannot read folder: {exc}")
            return
        if added:
            self._ensure_pool_applied()
        self._notify(f"Loaded {added} image(s) from {folder}"
                     + (f" ({skipped} more skipped)" if skipped else "")
                     + (f", {failed} unreadable" if failed else ""))
        if added:
            self._rerun()

    @pyqtSlot(int)
    def selectImage(self, index):  # noqa: N802
        self.engine.select_image(index)
        self._rerun()

    @pyqtSlot()
    def clearImages(self):  # noqa: N802
        self._pool.clear()
        self.engine.batch = None
        self._notify("Cleared image list")

    @pyqtSlot(str)
    def setScope(self, scope):  # noqa: N802
        self._scope = scope

    # ------------------------------------------------------------------ execution
    def _rerun(self) -> None:
        """Re-run the flow after an edit (queued if a cycle is already running)."""
        self.engine.request_run()

    @pyqtSlot()
    def run(self):
        """The Run button: 'Run all' over every image (repeating with Loop), else the selected one."""
        if self.engine.is_strip_busy():
            return
        self.engine.start_strip_run(self._scope, self._loop)

    @pyqtSlot()
    def stop(self):
        self.engine.stop()
        self._notify("Stopped")

    def _on_cycle(self, payload: dict) -> None:
        results = payload["results"]
        pipe = self._pipeline
        self._verdict = "PASS" if RunEngine.payload_ok(payload) and not payload["failure"] else "FAIL"
        self._flow_ms = float(pipe.last_flow_time_ms)
        self._algo_ms = sum(float(r.elapsed_ms) for r in results.values())
        image = None
        for nid in pipe.execution_order:
            res = results.get(nid)
            if res is not None and res.outputs.get("Image") is not None:
                image = res.outputs["Image"]
        self._last_image = image
        self._last_results = dict(results)
        self._formatted = format_flow_outputs(pipe, results)
        self._render_view()
        self._refresh_results()
        error = payload["script_error"] or payload["failure"]
        if error:
            self._notify(error)
        else:
            # keep the edit that triggered this run visible next to the verdict
            edit = self._hint.split("  ·  Flow executed")[0]
            ran = f"Flow executed: {self._verdict}"
            self._notify(f"{edit}  ·  {ran}" if edit and not edit.startswith("Flow executed") else ran)

    def _refresh_results(self):
        res = self._pipeline.last_results.get(self._selected)
        rows = []
        if res is not None:
            for k, v in res.outputs.items():
                if isinstance(v, (bool, int, float, str)):
                    rows.append({"name": k, "value": f"{v:.4g}" if isinstance(v, float) else str(v)})
        self._results = rows
