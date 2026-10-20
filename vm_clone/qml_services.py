"""QML-facing services for the tool dialogs.

Each class is a small QObject exposed to QML as a context property (``appLens``, ``appCamera``,
``appPlugins``, ``appInspection``).  They wrap the front-end independent engines - the sessions in
``vm_clone.core.sessions``, the plugin SDK and the evaluation controller - and talk to the main
``AppBackend`` only for the active flow, undo and status messages.  Like the backend they fall back
to sample data in the QML when absent, which keeps Qt Design Studio working.
"""
import os
import threading
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot

from vm_clone.core.sessions import CameraSession, LensSession, apply_lens_calibration
from vm_clone.qml_ai import AIGenService
from vm_clone.qml_backend import AppBackend, FrameProvider


def _path(url: str) -> str:
    return QUrl(url).toLocalFile() or url


# =============================================================================
# Lens calibration
# =============================================================================
class LensService(QObject):
    changed = pyqtSignal()

    def __init__(self, app: AppBackend, provider: FrameProvider):
        super().__init__()
        self._app, self._provider = app, provider
        self.session = LensSession()
        self._current = -1
        self._mode = LensSession.PREVIEW_MODES[0]
        self._status = "Add calibration views (files, synthetic or live), then compute."
        self._token = 0

    def _refresh_preview(self) -> None:
        self._provider.set_array(self.session.preview(self._current, self._mode))
        self._token += 1
        self.changed.emit()

    @pyqtProperty("QVariantList", notify=changed)
    def views(self):
        return [{"name": v["name"], "ok": v["ok"], "corners": v["corners"]} for v in self.session.views]

    @pyqtProperty(int, notify=changed)
    def currentView(self):  # noqa: N802
        return self._current

    @pyqtProperty(str, notify=changed)
    def mode(self):
        return self._mode

    @pyqtProperty("QVariantMap", notify=changed)
    def result(self):
        return self.session.result()

    @pyqtProperty(str, notify=changed)
    def status(self):
        return self._status

    @pyqtProperty(str, notify=changed)
    def previewUrl(self):  # noqa: N802
        return f"image://lens/{self._token}"

    @pyqtProperty("QVariantMap", notify=changed)
    def pattern(self):
        s = self.session
        return {"type": s.pattern, "cols": s.cols, "rows": s.rows, "squareMm": s.square_mm}

    @pyqtSlot(str, int, int, float)
    def setPattern(self, kind, cols, rows, square_mm):  # noqa: N802
        s = self.session
        s.pattern, s.cols, s.rows, s.square_mm = kind, max(3, cols), max(3, rows), max(0.1, square_mm)
        self.changed.emit()

    def _after_add(self, ok: bool, message: str) -> None:
        self._current = len(self.session.views) - 1
        self._status = message if ok else f"NG: {message}"
        self._refresh_preview()

    @pyqtSlot("QVariantList")
    def addFiles(self, urls):  # noqa: N802
        added = self.session.add_files([_path(str(u)) for u in urls])
        self._current = len(self.session.views) - 1
        self._status = f"Added {added} view(s)"
        self._refresh_preview()

    @pyqtSlot()
    def addSynthetic(self):  # noqa: N802
        self._after_add(*self.session.add_synthetic())

    @pyqtSlot()
    def capture(self):
        """Take the flow's current image as a calibration view."""
        image = self._app.currentFlowImage()
        if image is None:
            self._status = "No live or flow image available - load files or generate synthetic views"
            self.changed.emit()
            return
        self._after_add(*self.session.add_image(image, f"Captured Frame {len(self.session.views) + 1}"))

    @pyqtSlot(int)
    def remove(self, row):
        self.session.remove(row)
        self._current = min(self._current, len(self.session.views) - 1)
        self._refresh_preview()

    @pyqtSlot()
    def clear(self):
        self.session.clear()
        self._current = -1
        self._status = "Cleared"
        self._refresh_preview()

    @pyqtSlot(int)
    def selectView(self, row):  # noqa: N802
        self._current = row
        self._refresh_preview()

    @pyqtSlot(str)
    def setMode(self, mode):  # noqa: N802
        self._mode = mode
        self._refresh_preview()

    @pyqtSlot()
    def compute(self):
        if not any(v["ok"] for v in self.session.views):
            self._status = "Add at least 1 view with a detected pattern first"
            self.changed.emit()
            return
        ok, message = self.session.compute()
        self._status = message
        self._refresh_preview()

    @pyqtSlot(str)
    def saveProfile(self, url):  # noqa: N802
        if not self.session.calibrated:
            self._status = "Compute or load a calibration first"
        else:
            path = _path(url)
            if not path.lower().endswith(".json"):
                path += ".calib.json"
            self.session.save(path)
            self._status = f"Profile saved to {path}"
        self.changed.emit()

    @pyqtSlot(str)
    def loadProfile(self, url):  # noqa: N802
        ok = self.session.load(_path(url))
        self._status = "Profile loaded" if ok else "Could not read that calibration profile"
        self._refresh_preview()

    @pyqtSlot()
    def apply(self):
        if not self.session.calibrated:
            self._status = "Compute or load a valid calibration first"
            self.changed.emit()
            return
        self._app.editWith(lambda pipe: apply_lens_calibration(pipe, self.session.model.to_dict()),
                           "Lens calibration applied to the active flow")
        self._status = "Applied to the active flow"
        self.changed.emit()


# =============================================================================
# Camera
# =============================================================================
class CameraService(QObject):
    changed = pyqtSignal()

    def __init__(self, app: AppBackend, provider: FrameProvider):
        super().__init__()
        self._app, self._provider = app, provider
        self.session = CameraSession(self)
        self.session.frame.connect(self._on_frame)
        self.session.status.connect(self._set_status)
        self._devices: List[Dict[str, str]] = []
        self._selected = -1
        self._status = "Standby"
        self._token = 0
        self._previewing = False

    def _set_status(self, text: str) -> None:
        self._status = text
        self.changed.emit()

    def _on_frame(self, frame) -> None:
        self._provider.set_array(frame)
        self._token += 1
        self.changed.emit()

    @pyqtProperty("QVariantList", notify=changed)
    def devices(self):
        return self._devices

    @pyqtProperty(int, notify=changed)
    def selected(self):
        return self._selected

    @pyqtProperty(str, notify=changed)
    def status(self):
        return self._status

    @pyqtProperty(bool, notify=changed)
    def previewing(self):
        return self._previewing

    @pyqtProperty(str, notify=changed)
    def sdkStatus(self):  # noqa: N802
        try:
            return f"Hikrobot MVS C SDK: {self.session.sdk_status()}"
        except Exception as exc:
            return f"Camera subsystem unavailable: {exc}"

    @pyqtProperty(str, notify=changed)
    def previewUrl(self):  # noqa: N802
        return f"image://camera/{self._token}"

    @pyqtSlot()
    def refresh(self):
        try:
            self._devices = self.session.devices(refresh=True)
            self._status = f"{len(self._devices)} device(s) found"
        except Exception as exc:
            self._devices, self._status = [], f"Scan failed: {exc}"
        self.changed.emit()

    @pyqtSlot(int)
    def select(self, index):
        if not (0 <= index < len(self._devices)):
            return
        self._previewing = False
        self._selected = index
        ok = self.session.select(self._devices[index]["id"])
        self._status = "Ready" if ok else "Could not open that camera"
        self.changed.emit()

    @pyqtSlot(float, float, str, str)
    def setParams(self, exposure_us, gain, trigger, pixel_format):  # noqa: N802
        self.session.apply(exposure_us, gain, trigger, pixel_format)

    @pyqtSlot()
    def startPreview(self):  # noqa: N802
        self._previewing = self.session.start_preview()
        if not self._previewing:
            self._status = "Select a camera first"
        self.changed.emit()

    @pyqtSlot()
    def stopPreview(self):  # noqa: N802
        self.session.stop_preview()
        self._previewing = False
        self._status = "Standby"
        self.changed.emit()

    @pyqtSlot(str)
    def addStream(self, url):  # noqa: N802
        if url.strip():
            self.session._mgr().add_network_stream(url.strip())
            self.refresh()

    @pyqtSlot(str)
    def importMvs(self, url):  # noqa: N802
        ok = bool(self.session.device_id) and self.session._mgr().import_mvs_config(self.session.device_id, _path(url))
        self._set_status("MVS configuration imported" if ok else "Import failed")

    @pyqtSlot(str)
    def exportMvs(self, url):  # noqa: N802
        ok = bool(self.session.device_id) and self.session._mgr().export_mvs_config(self.session.device_id, _path(url))
        self._set_status("MVS configuration exported" if ok else "Export failed")

    @pyqtSlot()
    def shutdown(self):
        self.session.stop_preview()


# =============================================================================
# Plugins
# =============================================================================
class PluginService(QObject):
    changed = pyqtSignal()
    _done = pyqtSignal()

    def __init__(self, app: AppBackend):
        super().__init__()
        self._app = app
        self._log = ""
        self._busy = False
        self._result = None
        self._done.connect(self._on_done)

    def _pm(self):
        from vm_clone.sdk.manager import PluginManager
        return PluginManager.get_instance()

    def _market(self):
        from vm_clone.sdk.marketplace import MarketplaceService
        return MarketplaceService.get_instance()

    def _say(self, text: str) -> None:
        self._log += text + "\n"
        self.changed.emit()

    @pyqtProperty("QVariantList", notify=changed)
    def installed(self):
        out = []
        for rec in self._pm().list_plugins():
            d = rec.to_dict()
            out.append({"id": d["plugin_id"], "name": d["name"], "version": d["version"],
                        "category": d["category"], "status": d["state"],
                        "detail": f"{d['description']}\n\nTools: {', '.join(d['tool_names']) or '-'}"
                                  + (f"\nError: {d['error_message']}" if d["error_message"] else "")})
        return out

    @pyqtProperty("QVariantList", notify=changed)
    def marketplace(self):
        try:
            return [{"id": i.id, "name": i.name, "author": i.author, "version": i.version,
                     "status": ("Update" if i.has_update else "Installed") if i.is_installed else "Available",
                     "url": i.github_url} for i in self._market().get_catalog()]
        except Exception as exc:
            self._log += f"Catalog unavailable: {exc}\n"
            return []

    @pyqtProperty(str, notify=changed)
    def log(self):
        return self._log

    @pyqtProperty(bool, notify=changed)
    def busy(self):
        return self._busy

    @pyqtSlot()
    def rescan(self):
        self._pm().discover_and_load_all(reload=True)
        self._say("Rescanned plugin folders")
        self._app.toolsChanged()

    @pyqtSlot(str)
    def unload(self, plugin_id):
        ok = self._pm().unload_plugin(plugin_id)
        self._say(f"Unloaded {plugin_id}" if ok else f"Could not unload {plugin_id}")
        self._app.toolsChanged()

    @pyqtSlot(str)
    def loadFolder(self, url):  # noqa: N802
        folder = _path(url)
        try:
            rec = self._pm().load_plugin_from_directory(folder, reload=True)
        except Exception as exc:
            self._say(f"Load failed: {exc}")
            return
        self._say(f"Loaded {rec.metadata.name}" if rec else f"No valid plugin in {folder}")
        self._app.toolsChanged()

    def _run_async(self, job, then) -> None:
        if self._busy:
            return
        self._busy = True
        self.changed.emit()

        def work():
            try:
                self._result = (then, job())
            except Exception as exc:  # network / filesystem problems are reported, not raised
                self._result = (then, (False, f"{type(exc).__name__}: {exc}", None))
            try:
                self._done.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name="plugin-job").start()

    def _on_done(self):
        then, result = self._result or (None, None)
        self._busy = False
        if then is not None:
            then(result)
        self.changed.emit()

    @pyqtSlot(str, str)
    def installGithub(self, url, branch):  # noqa: N802
        if not url.strip():
            self._say("Enter a GitHub repository URL")
            return
        self._say(f"Downloading {url} ({branch or 'main'}) ...")
        self._run_async(lambda: self._market().install_from_github(url.strip(), branch.strip() or "main"),
                        self._finish_install)

    @pyqtSlot(str)
    def installMarketplace(self, plugin_id):  # noqa: N802
        item = next((i for i in self._market().get_catalog() if i.id == plugin_id), None)
        if item is None:
            self._say("Plugin not found in the catalog")
            return
        self.installGithub(item.github_url, "main")

    def _finish_install(self, result) -> None:
        ok, message, _record = result
        self._say(("Installed: " if ok else "Failed: ") + str(message))
        self._app.toolsChanged()

    @pyqtSlot(str, str, str, str, str, str, str)
    def scaffold(self, folder_url, plugin_id, name, author, category, tool, description):
        ok, message, path = self._market().scaffold_plugin(_path(folder_url), plugin_id, name, author,
                                                           category, tool, description)
        self._say(f"Created {path}" if ok else f"Failed: {message}")

    @pyqtSlot(str)
    def package(self, folder_url):
        ok, message, path = self._market().package_plugin(_path(folder_url))
        self._say(f"Packaged {path}" if ok else f"Failed: {message}")


# =============================================================================
# Inspection / evaluation
# =============================================================================
class InspectionService(QObject):
    changed = pyqtSignal()
    _progress = pyqtSignal(int, int, str)
    _finished = pyqtSignal()

    def __init__(self, app: AppBackend, provider: FrameProvider, store_directory: str = ""):
        super().__init__()
        from vm_clone.ui.inspection_controller import InspectionController
        self._app, self._provider = app, provider
        self.controller = InspectionController(store_directory=store_directory)
        self._busy = False
        self._cancel = False
        self._progress_text = ""
        self._progress_value = 0.0
        self._error = ""
        self._filter = {"kind": "", "label": "", "min_score": 0.0}
        self._comparison: Dict[str, Any] = {}
        self._case_token = 0
        self._outcome_error: Optional[str] = None
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

    # ---- properties
    @pyqtProperty(bool, notify=changed)
    def busy(self):
        return self._busy

    @pyqtProperty(str, notify=changed)
    def error(self):
        return self._error

    @pyqtProperty(float, notify=changed)
    def progress(self):
        return self._progress_value

    @pyqtProperty(str, notify=changed)
    def progressText(self):  # noqa: N802
        return self._progress_text

    @pyqtProperty(str, notify=changed)
    def storeDirectory(self):  # noqa: N802
        return self.controller.store_directory

    @pyqtProperty(str, notify=changed)
    def datasetText(self):  # noqa: N802
        s = self.controller.dataset_summary()
        if not s:
            return "No dataset loaded."
        return (f"{s['name']}: {s.get('images', 0)} images ({s.get('empty_images', 0)} clean), "
                f"{s.get('annotations', 0)} boxes, classes: {', '.join(s['classes'])}")

    @pyqtProperty("QVariantList", notify=changed)
    def metrics(self):
        return [{"name": n, "value": v} for n, v in self.controller.metrics_table()]

    @pyqtProperty("QVariantList", notify=changed)
    def perClass(self):  # noqa: N802
        keys = ("cls", "gt", "tp", "fp", "fn", "p", "r", "f1", "ap")
        return [dict(zip(keys, row)) for row in self.controller.per_class_rows()]

    @pyqtProperty("QVariantList", notify=changed)
    def labels(self):
        return ["All"] + self.controller.available_labels()

    def _filtered(self):
        from vm_clone.ui.inspection_controller import filter_failures
        f = self._filter
        return filter_failures(self.controller.failures,
                               kinds=[f["kind"]] if f["kind"] else None,
                               labels=[f["label"]] if f["label"] else None,
                               min_score=f["min_score"] or None)

    @pyqtProperty("QVariantList", notify=changed)
    def failures(self):
        return [{"image": c.image, "cls": c.label, "kind": c.kind, "reason": c.reason,
                 "score": "-" if c.score is None else f"{c.score:.2f}"} for c in self._filtered()]

    @pyqtProperty(str, notify=changed)
    def failureSummary(self):  # noqa: N802
        from vm_clone.ui.inspection_controller import failure_summary
        if not self.controller.failures:
            return "Run an evaluation to list failures."
        s = failure_summary(self._filtered())
        return f"{s['total']} failure(s): " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_kind"].items()))

    @pyqtProperty(str, notify=changed)
    def caseImageUrl(self):  # noqa: N802
        return f"image://inspect/{self._case_token}"

    @pyqtProperty("QVariantList", notify=changed)
    def experiments(self):
        out = []
        for e in self.controller.list_experiments():
            m = e.metrics or {}
            out.append({"name": e.name, "when": e.timestamp[:16].replace("T", " "),
                        "map": _fmt(m.get("map50")), "f1": _fmt(m.get("f1"))})
        return out

    @pyqtProperty("QVariantMap", notify=changed)
    def comparison(self):
        return self._comparison

    # ---- dataset
    @pyqtSlot(str)
    def loadDataset(self, url):  # noqa: N802
        try:
            self.controller.load_dataset(_path(url))
            self._error = ""
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
        self.changed.emit()

    @pyqtSlot(str, int)
    def generateDataset(self, folder_url, count):  # noqa: N802
        from vm_clone.samples.pcb_defect_dataset import build_dataset
        target = os.path.join(_path(folder_url), "pcb_defect_synth")
        try:
            build_dataset(target, count=max(4, count))
            self.controller.load_dataset(os.path.join(target, "annotations.json"))
            self._error = ""
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
        self.changed.emit()

    # ---- running
    @pyqtSlot(str, str, float, float, bool)
    def run(self, source, variant, iou, confidence, use_layout):
        if self._busy:
            return
        if self.controller.dataset is None:
            self._error = "Load or generate a dataset first"
            self.changed.emit()
            return
        self._busy, self._cancel, self._error = True, False, ""
        self._progress_value, self._progress_text = 0.0, "Starting..."
        self.changed.emit()
        pipeline = self._app.activePipeline() if source == "Active workflow" else None

        def progress(done, total, name):
            try:
                self._progress.emit(done, total, name)
            except RuntimeError:
                pass

        def work():
            try:
                self.controller.run_evaluation(detector_variant=variant, iou_threshold=iou,
                                               confidence_threshold=confidence, pipeline=pipeline,
                                               progress=progress, should_cancel=lambda: self._cancel,
                                               use_layout=use_layout)
                self._outcome_error = None
            except Exception as exc:
                self._outcome_error = f"{type(exc).__name__}: {exc}"
            try:
                self._finished.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name="evaluation").start()

    def _on_progress(self, done, total, name):
        self._progress_value = done / total if total else 0.0
        self._progress_text = f"{done}/{total} - {name}"
        self.changed.emit()

    def _on_finished(self):
        self._busy = False
        self._error = self._outcome_error or ""
        self._progress_text = "Done" if not self._error else ""
        self.changed.emit()

    @pyqtSlot()
    def cancel(self):
        self._cancel = True

    # ---- results
    @pyqtSlot(str, str, float)
    def setFilter(self, kind, label, min_score):  # noqa: N802
        self._filter = {"kind": "" if kind in ("", "All") else kind, "label": "" if label in ("", "All") else label,
                        "min_score": float(min_score)}
        self.changed.emit()

    @pyqtSlot(int)
    def showCase(self, row):  # noqa: N802
        import cv2
        from vm_clone.core.imageio import imread
        cases = self._filtered()
        if not (0 <= row < len(cases)):
            return
        case = cases[row]
        image = imread(case.image_path)
        if image is None:
            self._provider.set_array(None)
        else:
            x, y, w, h = [int(v) for v in case.box]
            colour = (0, 0, 255) if case.kind != "FN" else (0, 200, 255)
            cv2.rectangle(image, (x, y), (x + w, y + h), colour, 2)
            cv2.putText(image, f"{case.kind} {case.label}", (x, max(14, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2)
            self._provider.set_array(image)
        self._case_token += 1
        self.changed.emit()

    @pyqtSlot(str)
    def saveExperiment(self, name):  # noqa: N802
        try:
            exp = self.controller.save_experiment(name=name.strip(), pipeline=self._app.activePipeline())
            self._error = ""
            self._app.notify(f"Experiment saved: {exp.name}")
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
        self.changed.emit()

    @pyqtSlot(result=str)
    def storeDirectoryUrl(self):  # noqa: N802
        """The experiment folder as a file URL (created on demand) for the system file browser."""
        d = self.controller.store_directory
        if d:
            os.makedirs(d, exist_ok=True)
        return QUrl.fromLocalFile(d).toString() if d else ""

    @pyqtSlot(str)
    def setStore(self, url):  # noqa: N802
        self.controller.store_directory = _path(url)
        self.changed.emit()

    @pyqtSlot()
    def refreshExperiments(self):  # noqa: N802
        self.changed.emit()

    @pyqtSlot(str, str)
    def compare(self, base_name, other_name):
        exps = {e.name: e for e in self.controller.list_experiments()}
        if base_name not in exps or other_name not in exps or base_name == other_name:
            self._comparison = {"rows": [], "warnings": ["Pick two different experiments"]}
        else:
            try:
                cmp = self.controller.compare_experiments([exps[base_name], exps[other_name]],
                                                          allow_incomparable=True)
                rows = []
                base_row, other_row = cmp.rows[0], cmp.rows[-1]
                for key in ("precision", "recall", "f1", "map50"):
                    a, b = _num(base_row.metrics.get(key)), _num(other_row.metrics.get(key))
                    rows.append({"metric": key, "base": _fmt(a), "other": _fmt(b),
                                 "delta": "n/a" if a is None or b is None else f"{b - a:+.4f}"})
                self._comparison = {"rows": rows, "warnings": list(cmp.warnings) + list(cmp.observations)}
            except Exception as exc:
                self._comparison = {"rows": [], "warnings": [f"{type(exc).__name__}: {exc}"]}
        self.changed.emit()

    @pyqtSlot(result=str)
    def reportText(self):  # noqa: N802
        lines = [f"{n}: {v}" for n, v in self.controller.metrics_table()]
        return "\n".join(lines) or "No evaluation has been run."


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v) -> str:
    n = _num(v)
    return "n/a" if n is None else f"{n:.3f}"


# =============================================================================
# Wiring
# =============================================================================
def install_services(engine, app: AppBackend, store_directory: Optional[str] = None) -> Dict[str, QObject]:
    """Create the services, register their image providers and context properties on ``engine``.

    Returns them (the caller must keep the dict alive for as long as the engine runs)."""
    providers = {name: FrameProvider() for name in ("lens", "camera", "inspect")}
    for name, provider in providers.items():
        engine.addImageProvider(name, provider)
    store = store_directory if store_directory is not None else os.path.join(app.projectsDirectory(), "experiments")
    services: Dict[str, QObject] = {
        "appLens": LensService(app, providers["lens"]),
        "appCamera": CameraService(app, providers["camera"]),
        "appPlugins": PluginService(app),
        "appInspection": InspectionService(app, providers["inspect"], store),
        "appAI": AIGenService(app),
        "_providers": providers,                       # keep the providers referenced
    }
    for name, obj in services.items():
        if isinstance(obj, QObject):
            engine.rootContext().setContextProperty(name, obj)
    return services
