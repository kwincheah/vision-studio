"""Python backend for the QML user interface (``qml/``).

The QML screens are pure presentation; this object feeds them the real solution (flows,
wiring, layout, results, the current image) and executes their commands.  It is exposed to
QML as the context property ``appBackend`` - when it is absent (Qt Design Studio) the
screens fall back to ``ApexTheme/SampleData.qml``.

Everything here is Qt-widget free, so it works with ``QGuiApplication`` only.
"""
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np
from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage
from PyQt6.QtQuick import QQuickImageProvider

import apex_vision.tools  # noqa: F401  (registers the tools)
from apex_vision.core import param_schema
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


def _is_picture(value) -> bool:
    """Only an image array can be shown (a list or number wired into an Image input is not one)."""
    return isinstance(value, np.ndarray) and value.ndim in (2, 3)


class AppBackend(QObject):
    #: The Display Setup colour every module starts with (the signature amber).  Kept here
    #: so the render path does not need to import the tool base.
    DEFAULT_OVERLAY_COLOUR = "#e4b030"

    changed = pyqtSignal()
    startPageRequested = pyqtSignal()
    workspaceRequested = pyqtSignal()
    _all_cycle = pyqtSignal(str, object)    # a flow finished one cycle inside Run all flows (flow name, payload)
    _all_done = pyqtSignal()
    closeApproved = pyqtSignal()            # the window may close (nothing unsaved, or the user decided)
    confirmRequested = pyqtSignal(str)      # unsaved edits would be lost - ask the user first
    commMessage = pyqtSignal(str, str)      # a communication device with a flow to run received a message (device, text)

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
        self._flow_stats: dict = {}             # flow name -> (verdict, ms) of its last run, for the flow tabs
        self._algo_ms = 0.0
        self._results: List[Dict[str, str]] = []
        self._scope = "Run all"
        self._loops: Dict[str, bool] = {}        # Loop of each flow (the buttons next to the image and in the flow row)
        # Run all flows (the top buttons): its own state, separate from the single-flow Run of the open flow
        self._all_active = False
        self._all_stop = False
        self._all_loop = False
        self._all_flows: List[str] = []           # the flows the all-flows run is currently working on
        self._all_summary: Dict[str, str] = {}
        self._rerun_later = False
        self._undo: List[str] = []
        #: runtime variable values as last written to disk (see flushRuntimeState)
        self._runtime_saved: dict = {}
        #: True between a project load and the automatic first run it triggers (see _on_cycle)
        self._clean_after_load: bool = False
        self._redo: List[str] = []
        self._cameras: List[Dict[str, str]] = []
        self._pending = None                      # action waiting for the unsaved-changes answer
        self._last_image = None
        self._last_results: Dict[str, Any] = {}
        self._history: List[Dict[str, Any]] = []   # one entry per finished run, oldest first
        self._layers: Dict[str, bool] = dict(DEFAULT_LAYERS)
        self._formatted = ""
        # run / loop / stop / image pool are the shared controller - the same code the widget UI uses
        self._pool = ImagePool()
        self.engine = RunEngine(get_pipeline=lambda: self._pipeline, get_solution=lambda: self._solution,
                                pool=self._pool, interval_ms=lambda: int(self._pipeline.run_interval_ms),
                                parent=self)
        self.engine.cycle_finished.connect(self._on_cycle)
        self.commMessage.connect(self._on_comm_message)
        self._all_cycle.connect(self._on_all_cycle)
        self._all_done.connect(self._on_all_done)
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
        from apex_vision.core import comm_manager
        if comm_manager.get_manager().dump() != self._solution.comm_devices:        # undo/redo of adding or removing a device
            comm_manager.get_manager().load(self._solution.comm_devices)
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
        if self._all_live():                         # inside a Run all flows: is the open flow one of those running
            return self._solution.active_flow_name in self._all_flows
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
        if res is not None and _is_picture(res.outputs.get("Image")):
            return res.outputs["Image"], res.overlays
        node = pipe.nodes.get(self._selected)
        if node is not None:                      # modules without an image output show their input
            for c in pipe.connections:
                if c.to_node == self._selected and c.to_port == "Image":
                    upstream = self._last_results.get(c.from_node)
                    if upstream is not None and _is_picture(upstream.outputs.get(c.from_port)):
                        return upstream.outputs[c.from_port], (res.overlays if res else [])
        overlays = [o for r in self._last_results.values() for o in r.overlays]
        return self._last_image, overlays

    def _render_view(self) -> None:
        image, overlays = self._view_image_and_overlays()
        overlays = self._apply_module_display(overlays)
        self._provider.set_array(render_overlays(image, overlays, self._layers))
        self._token += 1

    def _apply_module_display(self, overlays):
        """Filter and recolour the selected module's overlays for its Display Setup.

        The ROI rectangle of the selected module is drawn by the view, not here, so these
        switches cover what the module itself paints: its text labels and its result boxes.
        Only the *selected* module is affected - the viewer shows that module's output.
        """
        node = self._pipeline.nodes.get(self._selected)
        if node is None or not overlays:
            return overlays
        display = node.display or {}
        show_labels = display.get("labels", True)
        show_boxes = display.get("boxes", True)
        colour = display.get("colour") or ""
        recolour = colour.lower() != self.DEFAULT_OVERLAY_COLOUR
        out = []
        for item in overlays:
            if not isinstance(item, dict):
                out.append(item)
                continue
            kind = item.get("type")
            if kind == "text" and not show_labels:
                continue
            if kind == "rect" and not show_boxes:
                continue
            if recolour and kind in ("text", "rect", "line", "circle", "sector", "cross"):
                item = {**item, "color": colour}
            out.append(item)
        return out

    @pyqtProperty("QVariantMap", notify=changed)
    def selectedDisplay(self):
        """The selected module's Display Setup (checkboxes and colour)."""
        node = self._pipeline.nodes.get(self._selected)
        if node is None:
            return {}
        return {**(node.display or {})}

    @pyqtSlot(str, str, "QVariant", result=bool)
    def setModuleDisplay(self, node_id, key, value):  # noqa: N802
        """Change one Display Setup field of a module (a checkbox or the colour)."""
        node = self._pipeline.nodes.get(node_id)
        if node is None or not self._editable():
            return False
        if key not in ("roi", "labels", "boxes", "colour"):
            return False
        current = (node.display or {}).get(key)
        if key == "colour":
            if hasattr(value, "toVariant"):
                value = value.toVariant()
            colour = str(value or "").lower()
            if len(colour) != 7 or not colour.startswith("#"):
                return False
            try:
                int(colour[1:], 16)
            except ValueError:
                return False
            value = colour
        else:
            value = bool(value)
        if current == value:
            return True
        self._push_undo()
        node.display = {**(node.display or {}), key: value}
        self._render_view()
        self._notify("Display updated")
        self.changed.emit()
        return True

    @pyqtProperty(str, constant=True)
    def version(self):
        return APP_VERSION

    # ------------------------------------------------------------------ script editor
    @pyqtSlot(str, result=str)
    def highlightScript(self, source):  # noqa: N802
        """The script as HTML spans for the editor's syntax colouring.

        Python's own tokenizer does the classifying (see core/script_highlight), so quotes
        and multi-line strings are correct rather than guessed at with regular expressions.
        """
        from apex_vision.core import script_highlight
        return script_highlight.highlight(source)

    @pyqtSlot(str, result="QVariantMap")
    def checkScript(self, source):  # noqa: N802
        """Compile without running: {ok, line, message}, so the gutter can mark the line."""
        from apex_vision.core import script_highlight
        return script_highlight.check(source)

    @pyqtProperty(str, constant=True)
    def scriptHint(self):  # noqa: N802
        from apex_vision.core import script_highlight
        return script_highlight.describe_contract()

    @pyqtProperty(str, constant=True)
    def projectsFolder(self):  # noqa: N802
        """Where new projects go unless the user picks another folder (shown in the New Project dialog)."""
        return self._pm.default_projects_dir

    @pyqtProperty("QVariantList", notify=changed)
    def results(self):
        return self._results

    # ---- the Result tab, History and Help pages ------------------------------------
    HISTORY_LIMIT = 100
    _BAD_STATUSES = (ToolStatus.NG, ToolStatus.ERROR, ToolStatus.TIMEOUT)

    @staticmethod
    def _summary(outputs: Dict[str, Any], limit: int = 4) -> str:
        """The first few plain values of a module's outputs, e.g. ``Mean=54.8  StdDev=41.4``."""
        parts = []
        for key, value in outputs.items():
            if isinstance(value, bool) or isinstance(value, (int, str)) and not (isinstance(value, str) and len(value) > 24):
                parts.append(f"{key}={value}")
            elif isinstance(value, float):
                parts.append(f"{key}={value:.4g}")
            if len(parts) >= limit:
                break
        return "  ".join(parts)

    def _module_rows(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        pipe = self._pipeline
        rows = []
        for nid in pipe.execution_order:
            node = pipe.nodes.get(nid)
            if node is None:
                continue
            res = results.get(nid)
            name = node.name.replace("_", " ", 1)
            if res is None:
                rows.append({"id": nid, "name": name, "tool": node.tool_name, "status": "-", "ms": 0.0,
                             "message": "not run yet", "summary": "", "bad": False})
                continue
            rows.append({"id": nid, "name": name, "tool": node.tool_name, "status": res.status.value,
                         "ms": float(res.elapsed_ms), "message": res.message, "summary": self._summary(res.outputs),
                         "bad": res.status in self._BAD_STATUSES})
        return rows

    @pyqtProperty("QVariantList", notify=changed)
    def moduleResults(self):  # noqa: N802
        """Every module's last result, in run order (the top Result tab)."""
        return self._module_rows(self._pipeline.last_results)

    @pyqtProperty("QVariantList", notify=changed)
    def history(self):
        """Finished runs, newest first (the History tab)."""
        return list(reversed(self._history))

    @pyqtSlot()
    def clearHistory(self):  # noqa: N802
        self._history = []
        self._notify("History cleared")

    def _record_history(self, results: Dict[str, Any]) -> None:
        rows = self._module_rows(results)
        source = ""
        for nid, node in self._pipeline.nodes.items():
            res = results.get(nid)
            if node.tool_name == "Image Source" and res is not None and " from " in res.message:
                source = res.message.split(" from ", 1)[1]
                break
        number = (self._history[-1]["n"] + 1) if self._history else 1
        self._history.append({
            "n": number, "time": time.strftime("%H:%M:%S"), "source": source,
            "verdict": self._verdict, "flowMs": round(self._flow_ms, 2),
            "failed": ", ".join(r["name"] for r in rows if r["bad"]), "modules": rows,
        })
        del self._history[:-self.HISTORY_LIMIT]

    @pyqtProperty("QVariantMap", notify=changed)
    def selectedHelp(self):  # noqa: N802
        """What the selected module is and what each of its settings means (the Help tab)."""
        node = self._pipeline.nodes.get(self._selected)
        if node is None:
            return {}
        params = []
        for key, current in node.parameters.items():
            spec = param_schema.spec_for(node.tool_name, key, current)
            if spec["kind"] == "hidden":
                continue
            item = {"name": spec.get("label", key), "kind": spec["kind"], "value": str(current)[:40], "limits": ""}
            unit = f" {spec['unit']}" if spec.get("unit") else ""
            if spec.get("choices"):
                item["limits"] = " / ".join(str(c) for c in spec["choices"])
            elif "min" in spec and "max" in spec and abs(spec["min"]) < 1e11 and abs(spec["max"]) < 1e11:
                item["limits"] = f"{spec['min']:g} to {spec['max']:g}{unit}"
            elif unit:
                item["limits"] = unit.strip()
            params.append(item)
        return {
            "title": node.name.replace("_", " ", 1), "tool": node.tool_name, "category": node.category,
            "description": node.description or "",
            "inputs": [f"{n} ({p.data_type.value})" + (f" - {p.description}" if p.description else "") for n, p in node.inputs.items()],
            "outputs": [f"{n} ({p.data_type.value})" + (f" - {p.description}" if p.description else "") for n, p in node.outputs.items()],
            "parameters": params,
        }

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
        return bool(self._loops.get(self._solution.active_flow_name, False))

    def _set_loop(self, value: bool) -> None:
        self._loops[self._solution.active_flow_name] = bool(value)
        self.changed.emit()

    loop = pyqtProperty(bool, _get_loop, _set_loop, notify=changed)          # Loop of the open flow only

    def _get_all_loop(self) -> bool:
        return self._all_loop

    def _set_all_loop(self, value: bool) -> None:
        self._all_loop = bool(value)
        self.changed.emit()

    allLoop = pyqtProperty(bool, _get_all_loop, _set_all_loop, notify=changed)   # Loop of the top buttons: every flow

    @pyqtProperty(bool, notify=changed)
    def allRunning(self):  # noqa: N802
        return self._all_live()

    @pyqtProperty("QVariantList", notify=changed)
    def globalVariables(self):  # noqa: N802
        runtime = self._solution.runtime_globals
        return [{"name": k, "type": type(v).__name__, "value": str(v),
                 "runtime": k in runtime}
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
        icons = {"Acquisition": "camera", "Image Processing": "image", "Color Processing": "palette", "Location": "target", "Measurement": "measure",
                 "Image Generation": "roi", "Calibration": "grid", "Calculation": "variable", "Recognition": "text", "Defect Detection": "shield",
                 "Deep Learning": "layers", "Division and Combination": "table", "Logic Tools": "logic", "Communication": "comm"}
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

    @pyqtSlot(result=bool)
    def resetRoi(self):  # noqa: N802
        """Put the selected module's ROI back to "the whole image".

        ``[0, 0, 0, 0]`` is the tools' own default and means "no restriction" - the region
        tools treat an empty ROI as the full frame, so this is a real reset rather than a
        1x1 box parked in the corner.  One undo step, and the flow re-runs so the verdict
        follows the change.
        """
        node, key = self._roi_key()
        if key is None:
            self._notify("This module has no region to reset")
            return False
        if not self._editable():
            return False
        if list(node.parameters.get(key) or []) == [0, 0, 0, 0]:
            self._notify("ROI is already the whole image")
            return True
        self._push_undo()
        node.set_param(key, [0, 0, 0, 0])
        self._notify("ROI reset to the whole image")
        self._rerun()
        return True

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
                "group": pipe.group_of(nid),
                "inputs": [{"name": n, "type": _PORT_KIND.get(p.data_type, "region"), "dtype": p.data_type.name}
                           for n, p in node.inputs.items()],
                "outputs": [{"name": n, "type": _PORT_KIND.get(p.data_type, "region"), "dtype": p.data_type.name}
                            for n, p in node.outputs.items()],
            })
        return out

    @pyqtProperty("QVariantList", notify=changed)
    def groupFrames(self):  # noqa: N802
        """A frame round each Group's modules (for the canvas): {id, title, x, y, w, h}."""
        pipe = self._pipeline
        positions = self._positions(pipe)
        out = []
        for gid, g in pipe.nodes.items():
            if g.tool_name != "Group":
                continue
            ids = [gid] + pipe.group_members(gid)
            xs0, ys0, xs1, ys1 = [], [], [], []
            for nid in ids:
                n = pipe.nodes[nid]
                x, y = positions.get(nid, (50.0, 50.0))
                xs0.append(x)
                ys0.append(y)
                xs1.append(x + 190)
                ys1.append(y + 54 + 14 * max(len(n.inputs), len(n.outputs), 1))
            pad = 16
            out.append({"id": gid, "title": g.name.replace("_", " ", 1), "x": min(xs0) - pad, "y": min(ys0) - pad - 14, "w": max(xs1) - min(xs0) + 2 * pad,
                        "h": max(ys1) - min(ys0) + 2 * pad + 14, "count": len(ids) - 1})
        return out

    @pyqtSlot(str, result="QVariantList")
    def groupsFor(self, node_id):  # noqa: N802
        """The Group modules this module could be put in: [{id, title}] (none for a Group itself)."""
        node = self._pipeline.nodes.get(node_id)
        if node is None or node.tool_name == "Group":
            return []
        return [{"id": gid, "title": g.name.replace("_", " ", 1), "current": self._pipeline.group_of(node_id) == gid}
                for gid, g in self._pipeline.nodes.items() if g.tool_name == "Group"]

    @pyqtSlot(str, str, result=str)
    def setNodeGroup(self, node_id, group_id):  # noqa: N802
        """Put a module in a Group (or out of it with an empty id). Returns '' on success, else what is wrong. One undo step."""
        pipe = self._pipeline
        if node_id not in pipe.nodes:
            return "That module no longer exists."
        if not self._editable():
            return "Editing is locked for the Operator role."
        if pipe.group_of(node_id) == (group_id or ""):
            return ""
        if group_id and (group_id not in pipe.nodes or pipe.nodes[group_id].tool_name != "Group"):
            return "Choose a Group module."
        if pipe.nodes[node_id].tool_name == "Group":
            return "A Group cannot be put inside another Group."
        self._push_undo()
        pipe.set_group(node_id, group_id or "")
        shown = lambda n: n.replace("_", " ", 1)  # noqa: E731
        self._notify(f"{shown(pipe.nodes[node_id].name)} " + (f"added to {shown(pipe.nodes[group_id].name)}" if group_id else "taken out of its group"))
        self.changed.emit()
        return ""

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
    @staticmethod
    def uses_sample_images(solution: SolutionManager) -> bool:
        """True when a flow's Image Source is set up to show the bundled sample board (the built-in demo flows).

        Everything else (your own projects, cameras, folders, a plugin's own source module) starts with an empty image strip:
        the sample pictures would feed nothing and would make 'Run all' repeat the flow once per picture."""
        samples = os.path.normcase(os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples"))
        for flow in solution.flows.values():
            for node in flow.nodes.values():
                if node.tool_name != "Image Source":
                    continue
                kind = node.get_param("source_type", "Synthetic")
                if kind == "Synthetic" and node.get_param("pattern_type", "") in ("Part with Defects", "PCB Inspection"):
                    return True
                if kind == "File":
                    fp = str(node.get_param("file_path", "") or "").strip().strip('"')
                    if fp and os.path.normcase(os.path.abspath(fp)).startswith(samples):
                        return True
        return False

    def load_solution(self, solution: SolutionManager, path: Optional[str] = None, sample_images: Optional[bool] = None) -> None:
        """Open ``solution``. The image strip lists the bundled sample pictures only for the built-in demo flows;
        ``sample_images`` forces it on or off."""
        if sample_images is None:
            sample_images = self.uses_sample_images(solution)
        self._all_flows, self._all_loop, self._loops = [], False, {}        # another solution: nothing keeps running, Loop is off
        if self._all_active:
            self._all_stop = True
        self._solution = solution
        self._project.path = path
        self._start_comm(solution)
        self._selected = next(iter(self._pipeline.execution_order), "")
        self._results = []
        self._history = []
        self._undo.clear()
        self._redo.clear()
        self._freeze_layout()
        if sample_images:
            self._seed_sample_images()
        else:
            self._pool.clear()
            self.engine.batch = None
        self._project.mark_saved(solution)
        self._runtime_saved = self._runtime_values()
        self._clean_after_load = True          # the rerun() below is ours, not the operator's
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
        sol = SolutionManager(name="IndustrialSolution")          # empty: a sample board only comes with a template the user picks
        sol.flows["Flow1"] = self._blank_flow("Flow1")
        sol.active_flow_name = "Flow1"
        self.load_solution(sol, None, sample_images=False)
        if self._pm.get_show_on_startup():
            self.startPageRequested.emit()

    def _runtime_values(self):
        sol = self._solution
        return {k: sol.global_variables.get(k) for k in sol.runtime_globals
                if k in sol.global_variables}

    @pyqtSlot()
    def flushRuntimeState(self):  # noqa: N802
        """Write runtime values to the project without claiming they are unsaved edits.

        A run updates a lot tally, and the operator should not be asked to save that - but it
        should still be there tomorrow.  So when the document is otherwise clean and only
        runtime values moved, the file is written quietly.  Anything the operator changed
        makes the project dirty and takes the normal save path instead.
        """
        if self.dirty or not self._project.path or not self._solution.runtime_globals:
            return
        current = self._runtime_values()
        if current == getattr(self, "_runtime_saved", None):
            return
        try:
            self._project.save(self._solution, self._project.path)
            self._runtime_saved = dict(current)
            self._notify("Runtime values saved")
        except Exception as exc:                              # never block a close on this
            self._notify(f"Could not save runtime values: {exc}")

    @pyqtSlot()
    def requestClose(self):  # noqa: N802
        """The window asked to close: ask about unsaved edits first."""
        self._flush_runtime_then(self.closeApproved.emit)

    def _flush_runtime_then(self, action) -> None:
        if not self.dirty:
            self.flushRuntimeState()
        self._guard(action)

    #: Picture extensions the strip lists when it seeds itself from a sample folder.
    PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

    def _seed_sample_images(self) -> None:
        """List the bundled pictures that belong to the flow being opened.

        Each shipped demo keeps its pictures in its own folder under ``samples/``, so the strip
        shows the images that flow actually inspects: the PCB boards for the PCB demo, the good
        and mixed parts for the Parts Sorter. Previously the strip was hardcoded to the two PCB
        boards, which meant every other demo listed pictures its flow had nothing to do with.

        They are only listed - the Image Source keeps its own input until one is selected.
        """
        if len(self._pool):
            self._pool.clear()                       # opening another project: its pictures, not the last one's
        samples = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

        folder = None
        for node in self._pipeline.nodes.values():
            if node.tool_name != "Image Source" or node.get_param("source_type") != "File":
                continue
            path = str(node.get_param("file_path", "") or "").strip().strip('"')
            if not path:
                continue
            full = os.path.abspath(path)
            if not os.path.normcase(full).startswith(os.path.normcase(samples)):
                continue
            folder = os.path.dirname(full)
            break

        if folder and os.path.isdir(folder):
            for name in sorted(os.listdir(folder))[:12]:
                if name.lower().endswith(self.PICTURE_SUFFIXES):
                    self._pool.add_path(os.path.join(folder, name))

        if not len(self._pool):                      # no sample folder (or it is empty): the boards
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
        """``file:///C:/x/y.apex`` -> ``C:/x/y.apex`` (QML dialogs return URLs)."""
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
            path += ".apex"
        try:
            self._project.save(self._solution, path)
        except Exception as exc:
            self._notify(f"Save failed: {exc}")
            return
        self._runtime_saved = self._runtime_values()
        self._notify(f"Saved to {path}")

    @pyqtSlot(int)
    def newFromTemplate(self, index):  # noqa: N802
        template = ["pcb", "measurement", "yolo", "calibration"][max(0, min(index, 3))]

        def do():
            try:
                sol, path = self._pm.create_project(f"Solution_{template.upper()}", template=template)
            except OSError as exc:
                self._notify(f"Could not create the project: {exc}")
                return
            self.load_solution(sol, path)
        self._guard(do)

    @pyqtSlot(str, str, int)
    def createProject(self, name, folder, template):  # noqa: N802
        def do():
            try:
                sol, path = self._pm.create_project(name, folder, template=TEMPLATE_KEYS[max(0, min(template, 4))])
            except OSError as exc:        # unwritable or missing drive: tell the user instead of crashing
                self._notify(f"Could not create the project in '{folder}': {exc}")
                return
            self.load_solution(sol, path, sample_images=False if TEMPLATE_KEYS[max(0, min(template, 4))] == "blank" else None)
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

    @pyqtProperty("QVariantList", notify=changed)
    def flowTabs(self):  # noqa: N802
        """Every flow of the solution, for the tab bar: name, last verdict ('' = not run yet), cycle ms, active."""
        active = self._solution.active_flow_name
        tabs = []
        for name in self._solution.flows:
            verdict, ms = self._flow_stats.get(name, ("", 0.0))
            running = (name in self._all_flows) if self._all_live() else (name == active and self.engine.show_as_running()[0])
            tabs.append({"name": name, "verdict": verdict, "ms": round(ms), "active": name == active, "running": bool(running)})
        return tabs

    @pyqtSlot(str)
    def selectFlow(self, name):  # noqa: N802
        """Open another flow of the solution (its tab was clicked)."""
        if name not in self._solution.flows or name == self._solution.active_flow_name:
            return
        self.engine.stop()
        self._solution.active_flow_name = name
        self._verdict, self._flow_ms = self._flow_stats.get(name, ("PASS", 0.0))
        self._freeze_layout()
        self._selected = next(iter(self._pipeline.execution_order), "")
        self._notify(f"Opened flow {name}")
        self.workspaceRequested.emit()
        self._rerun()

    @pyqtSlot(str)
    def closeFlow(self, name):  # noqa: N802
        """Delete a flow (its tab's x). The last flow cannot be deleted; Ctrl+Z brings a deleted one back."""
        if not self._editable() or name not in self._solution.flows:
            return
        if len(self._solution.flows) < 2:
            self._notify("A solution needs at least one flow")
            return
        self._push_undo()
        was_active = name == self._solution.active_flow_name
        self._solution.remove_flow(name)
        self._flow_stats.pop(name, None)
        if was_active:
            self._verdict, self._flow_ms = self._flow_stats.get(self._solution.active_flow_name, ("PASS", 0.0))
            self._freeze_layout()
            self._selected = next(iter(self._pipeline.execution_order), "")
            self._rerun()
        self._notify(f"Deleted flow {name}")

    @staticmethod
    def _blank_source():
        """An Image Source with nothing chosen yet: it brings no sample picture."""
        src = create_tool_instance("Image Source", new_instance_id("src"), "01_Acquisition")
        src.set_param("source_type", "File")
        src.set_param("file_path", "")
        return src

    def _blank_flow(self, name: str):
        from apex_vision.core.pipeline import VisionPipeline
        flow = VisionPipeline(name=name)
        flow.add_node(self._blank_source())
        return flow

    @pyqtSlot()
    def addFlow(self):  # noqa: N802
        self._push_undo()
        n = len(self._solution.flows) + 1
        while f"Flow{n}" in self._solution.flows:
            n += 1
        flow = self._solution.add_flow(f"Flow{n}")
        flow.add_node(self._blank_source())
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

    # ------------------------------------------------------------------ communication management
    def _start_comm(self, solution: SolutionManager) -> None:
        """Make the network devices of the opened solution the live ones, and start those marked to start with it."""
        from apex_vision.core import comm_manager
        mgr = comm_manager.get_manager()
        mgr.on_message = lambda device, text: self.commMessage.emit(device, text)       # called on the device's thread; queued to the window's
        mgr.load(solution.comm_devices)
        problems = mgr.start_auto()
        if problems:
            self._notify("Communication: " + "; ".join(problems))

    def _on_comm_message(self, device: str, text: str) -> None:
        from apex_vision.core import comm_manager
        dev = comm_manager.get_manager().devices.get(device)
        if dev is None or not dev.trigger_flow:
            return
        self._solution.global_variables["g_LastMessage"] = text
        flow = self._solution.flows.get(dev.trigger_flow)
        if flow is not None and flow.enabled:
            if dev.trigger_flow == self._solution.active_flow_name:
                self.run()
            else:
                self._solution.trigger_flow(dev.trigger_flow)
            self.changed.emit()

    @pyqtProperty("QVariantList", notify=changed)
    def commDevices(self):  # noqa: N802
        from apex_vision.core import comm_manager
        return comm_manager.get_manager().status()

    @pyqtProperty("QVariantList", notify=changed)
    def flowNames(self):  # noqa: N802
        return list(self._solution.flows)

    @pyqtSlot()
    def refreshComm(self):  # noqa: N802
        self.changed.emit()

    @pyqtSlot(str, str, str, int, str, str, bool, str, result=str)
    def addCommDevice(self, name, kind, host, port, terminator, trigger_flow, auto_start, remote):  # noqa: N802
        """Add a network device to the solution. '' on success, else what is wrong."""
        from apex_vision.core import comm_manager
        if not self._editable():
            return "Editing is locked for the Operator role."
        mgr = comm_manager.get_manager()
        bad = mgr.add(comm_manager.CommDevice(name.strip(), kind, host.strip() or "0.0.0.0", port, terminator, trigger_flow, auto_start, remote.strip()))
        if bad:
            return bad
        self._push_undo()
        self._solution.comm_devices = mgr.dump()
        self.changed.emit()
        return ""

    @pyqtSlot(str, result=str)
    def startCommDevice(self, name):  # noqa: N802
        from apex_vision.core import comm_manager
        bad = comm_manager.get_manager().start(name)
        self.changed.emit()
        return bad or ""

    @pyqtSlot(str)
    def stopCommDevice(self, name):  # noqa: N802
        from apex_vision.core import comm_manager
        comm_manager.get_manager().stop(name)
        self.changed.emit()

    @pyqtSlot(str)
    def removeCommDevice(self, name):  # noqa: N802
        from apex_vision.core import comm_manager
        if not self._editable():
            return
        mgr = comm_manager.get_manager()
        self._push_undo()
        mgr.remove(name)
        self._solution.comm_devices = mgr.dump()
        self.changed.emit()

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

    @pyqtSlot(str, bool, result=bool)
    def setGlobalRuntime(self, name, runtime):  # noqa: N802
        """Mark a variable as runtime state rather than a setting.

        Runtime values are saved with the project but left out of the "unsaved changes"
        comparison, because the flow writes them on every run and that is the machine
        working, not the operator editing.  Marking is itself a document change.
        """
        if name not in self._solution.global_variables or not self._editable():
            return False
        if (name in self._solution.runtime_globals) == bool(runtime):
            return True
        self._push_undo()
        if runtime:
            self._solution.runtime_globals.add(name)
        else:
            self._solution.runtime_globals.discard(name)
        self._notify(f"{name} is now {'runtime state' if runtime else 'a saved setting'}")
        self.changed.emit()
        return True

    @pyqtSlot(str)
    def removeGlobal(self, name):  # noqa: N802
        if name in self._solution.global_variables and self._editable():
            self._push_undo()
            del self._solution.global_variables[name]
            self._solution.runtime_globals.discard(name)
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
        off = param_schema.inactive(node.tool_name, node.parameters)
        for k, v in node.parameters.items():
            spec = param_schema.spec_for(node.tool_name, k, v)
            if spec["kind"] == "hidden":
                continue
            if spec["kind"] == "flow":
                spec["choices"] = list(self._solution.flows)
            elif spec["kind"] == "device":
                spec["choices"] = self._camera_ids(v, node.parameters.get("source_type") if node.tool_name == "Image Source" else None)
            spec.update({"active": k not in off, "why": off.get(k, ""), "name": k, "type": type(v).__name__, "native": v,
                         "value": json.dumps(v) if isinstance(v, (list, dict)) else str(v)})
            out.append(spec)
        return out

    def _camera_ids(self, current: Any, source_type: Optional[str] = None) -> List[str]:
        """Camera ids to choose from; with a Source Type, only the devices that kind of source can use."""
        ids = []
        try:
            from apex_vision.core.camera_manager import CameraManager
            from apex_vision.tools.acquisition import device_fits
            ids = [d.device_id for d in CameraManager.get_instance().list_devices() if source_type is None or device_fits(source_type, d.camera_type)]
        except Exception:
            pass
        if current and current not in ids and source_type is None:
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
        if isinstance(value, str) and value.lower().endswith(".pt"):
            self._notify(f"{node.name}: a .pt model is converted to ONNX on first use. Only use models you trust - a .pt file can contain code.")
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

    def _adopt_pool_image(self, row=None) -> None:
        """The operator just loaded images: make the chosen one the project's source.

        Unlike ``_ensure_pool_applied`` this is a configuration change, so the Image
        Source's ``source_type`` / ``file_path`` are written and the project becomes dirty.
        Loading images is a deliberate edit; running a flow is not.
        """
        self._pool.apply_to(self._pipeline, row, persist=True)

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
            self._adopt_pool_image(first)
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
            self._adopt_pool_image()
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
        if self._all_active:                         # the all-flows run owns the flows: it shows the edit on its next pass
            self._rerun_later = True
            return
        self.engine.request_run()

    @pyqtSlot()
    def run(self):
        """The Run button of the open flow: 'Run all' over every image (repeating with Loop), else the selected one."""
        if self._all_live():                         # an all-flows run is going: this flow joins it
            name = self._solution.active_flow_name
            if name not in self._all_flows:
                self._all_flows.append(name)
                self._notify(f"{name} started")
            return
        if self.engine.is_strip_busy():
            return
        self.engine.start_strip_run(self._scope, self.loop)

    @pyqtSlot()
    def stop(self):
        """The Stop button of the open flow: only this flow (the others of an all-flows run carry on)."""
        if self._all_live():
            name = self._solution.active_flow_name
            if name in self._all_flows:
                self._all_flows.remove(name)
            if not self._all_flows:
                self._all_stop = True
            self.engine.stop()
            self._notify(f"{name} stopped" + ("" if self._all_flows else " - no flow is running"))
            return
        self.engine.stop()
        self._notify("Stopped")

    # ------------------------------------------------------------------ all flows (the top Run / Loop / Stop)
    def _all_live(self) -> bool:
        return self._all_active and not self._all_stop

    @pyqtSlot()
    def runAll(self):  # noqa: N802
        """Run every flow of the solution - repeating until Stop when the top Loop is on. Each flow reads its own Image Source."""
        names = [n for n, f in self._solution.flows.items() if f.enabled]
        if not names:
            return
        if self._all_live():                         # already running: bring in any flow that was stopped on its own
            self._all_flows.extend(n for n in names if n not in self._all_flows)
            self._notify(f"All {len(names)} flows running")
            return
        if self._all_active:                         # a stopped run is still finishing its last cycle
            return
        self.engine.stop()
        sol = self._solution
        self._all_flows, self._all_stop, self._all_active = names, False, True
        self._all_summary = {}
        self._rerun_later = False

        def work():
            while True:
                for name in list(self._all_flows):
                    if self._all_stop or self._solution is not sol:
                        break
                    flow = sol.flows.get(name)
                    if flow is None or name not in self._all_flows:
                        continue
                    while self.engine.busy and not self._all_stop:       # a single-flow cycle is finishing
                        time.sleep(0.02)
                    payload = RunEngine.compute_cycle(flow, sol)
                    try:
                        self._all_cycle.emit(name, payload)
                    except RuntimeError:             # the window closed
                        return
                if self._all_stop or self._solution is not sol or not self._all_loop or not self._all_flows:
                    break
                time.sleep(max(0.05, float(getattr(self._pipeline, "run_interval_ms", 0) or 0) / 1000.0))
            try:
                self._all_done.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()
        self._notify(f"Running all {len(names)} flows" + (" - Loop is on, press Stop to end" if self._all_loop else ""))

    @pyqtSlot()
    def stopAll(self):  # noqa: N802
        """Stop every flow (the top Stop button) - the open flow too."""
        self._all_stop = True
        self._all_flows = []
        self.engine.stop()
        self._notify("Stopped all flows")

    def _on_all_cycle(self, name: str, payload: dict) -> None:
        flow = self._solution.flows.get(name)
        if flow is None or flow is not payload["pipeline"]:         # the flow was deleted or replaced meanwhile
            return
        verdict = "PASS" if RunEngine.payload_ok(payload) and not payload["failure"] else "FAIL"
        self._all_summary[name] = verdict
        if name == self._solution.active_flow_name:
            self._on_cycle(payload)                  # the open flow shows its results as usual
        else:
            self._flow_stats[name] = (verdict, float(flow.last_flow_time_ms))
            self.changed.emit()

    def _on_all_done(self) -> None:
        stopped = self._all_stop
        self._all_active = self._all_stop = False
        self._all_flows = []
        if not stopped and self._all_summary:
            bad = sum(1 for v in self._all_summary.values() if v != "PASS")
            self._hint = f"All flows finished: {len(self._all_summary) - bad} PASS, {bad} FAIL"
        if self._rerun_later:
            self._rerun_later = False
            self.engine.request_run()
        self.changed.emit()

    def _on_cycle(self, payload: dict) -> None:
        results = payload["results"]
        pipe = self._pipeline
        self._verdict = "PASS" if RunEngine.payload_ok(payload) and not payload["failure"] else "FAIL"
        self._flow_ms = float(pipe.last_flow_time_ms)
        self._flow_stats[self._solution.active_flow_name] = (self._verdict, self._flow_ms)
        self._algo_ms = sum(float(r.elapsed_ms) for r in results.values())
        image = None
        for nid in pipe.execution_order:
            res = results.get(nid)
            if res is not None and _is_picture(res.outputs.get("Image")):
                image = res.outputs["Image"]
        self._last_image = image
        self._last_results = dict(results)
        self._record_history(results)
        self._formatted = format_flow_outputs(pipe, results)
        self._render_view()
        self._refresh_results()
        # Opening a project runs it once so the window is not blank.  Whatever that run wrote
        # (a script's global counter, say) is not an edit by the operator, so a project must not
        # be "modified" the moment it is opened.  Only adopt it when the operator has not done
        # anything yet - any real edit pushes an undo step, which rules this out.
        if self._clean_after_load:
            self._clean_after_load = False
            if not self._undo and not self._redo:
                self._project.mark_saved(self._solution)
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
