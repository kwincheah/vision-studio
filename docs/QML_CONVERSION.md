# Converting the widget UI to QML

**`python main.py` now starts the QML interface.** The classic widget interface remains available
with `python main.py --widgets`.

The application has two front ends over the same engine (`vm_clone/core`, `vm_clone/tools`):

| | Widget UI | QML UI |
|---|---|---|
| start | `python main.py` | `python qml_main.py` |
| code | `vm_clone/ui/*.py` (PyQt6 widgets + QSS) | `qml/` + `vm_clone/qml_backend.py` |
| edit visually | no | **Qt Design Studio** - open `qml/ApexVision.qmlproject` |

## The helper script
Double-click **`convert_qml.bat`** (or run `convert_qml <command>`):

| menu | command | does |
|---|---|---|
| 1 | `run` | start the QML UI on the real engine |
| 2 | `design` | open `qml\ApexVision.qmlproject` in Qt Design Studio |
| 3 | `dialog Name "Title" [Menu]` | scaffold a dialog: creates the QML file, registers it in `qmldir` and `DialogHost.qml`, adds the menu entry and the `invoke()` case, prints the backend stub to paste |
| 4 | `verify` | QML load / registration tests, then the whole suite |
| 5 | `icons` | regenerate the SVG icons |
| 6 | `shots` | render every screen to `docs\screenshots\qml` |
| 7 | `widget` | start the widget UI to compare against |

Example: `convert_qml dialog ExportReport "Export Report" File` creates `ExportReportDialog.qml`,
puts "Export Report..." in the File menu and wires it to open the dialog. Re-running is safe.

## One brain, two faces
Both front ends call the same widget-free code in **`vm_clone/core/controller.py`**, so a behaviour is
written - and fixed - once:

| class | owns |
|---|---|
| `ImagePool` | the image list, folder loading (natural order), feeding the Image Source |
| `RunEngine` | worker-thread execution, queued runs, **Run all / Loop / Stop**, Stop-on-NG, continuous-mode image cycling |
| `ProjectState` | current file, change tracking (dirty), save / open for VMP, JSON and XML |

The widget window (`main_window.py`) and the QML backend (`qml_backend.py`) only present these and
add UI-specific bits (dialogs, prompts, the scene). Anything new that is not about drawing belongs in
the controller. Flow-editing operations (`make_module`, `auto_wire_image`, `add_module`,
`connect_ports`) are shared too; the widget keeps its `QUndoStack` around them while the QML
backend uses snapshot undo. Still widget-only: camera and calibration handling, ROI on the
zoomed/panned image, plugin installation and the evaluation engine.

## How the conversion works

Each widget class becomes a QML file; the logic that used to live in the widget's slots moves
to a small method on `AppBackend`, and the QML calls it.

```
 widget class (vm_clone/ui/x.py)            QML file                          backend (qml_backend.py)
 ------------------------------            --------------------------------  ---------------------------
 QSS tokens (vm_theme.py THEME)        ->  qml/ApexTheme/Theme.qml
 QPushButton / QLineEdit / QComboBox   ->  qml/ApexComponents/*.qml
 QDialog subclass                      ->  qml/ApexDialogs/<Name>Dialog.qml  + a line in DialogHost.qml
 QMainWindow areas                     ->  qml/screens/*.qml
 QAction menu entry                    ->  an entry in SampleData.menus + a `case` in MainScreen.invoke()
 slot that mutates the solution        ->  @pyqtSlot on AppBackend
 data the widget shows                 ->  @pyqtProperty on AppBackend (QVariantList / QVariantMap)
```

### Port one dialog, step by step
1. **Component** - create `qml/ApexDialogs/MyDialog.qml` with `DialogFrame { title: ...; dialogWidth: ...}`.
   Put the body inside it and the buttons in `buttons: [ ... ]`. Use the parts in
   `ApexComponents` (`AppButton`, `TextBox`, `NumberBox`, `SelectBox`, `CheckLabel`, `DataTable`,
   `FormRow`, `SectionLabel`, tabs via `TabButton2`). Never write a colour - use `Theme.xxx`.
2. **Data** - declare
   `readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null` and bind
   to `backend.something` with `SampleData.something` as the fallback. Add the sample value to
   `ApexTheme/SampleData.qml` so the dialog renders in Design Studio.
3. **Register** - add `MyDialog 1.0 MyDialog.qml` to `ApexDialogs/qmldir` and one line to
   `DialogHost.qml`:
   `MyDialog { anchors.fill: parent; visible: host.current === "myDialog"; onClosed: host.close() }`.
4. **Open it** - add `{ text: "My Dialog...", key: "myDialog" }` to a menu in `SampleData.menus`
   and `case "myDialog": dialogs.show("myDialog"); break` in `MainScreen.invoke()`.
5. **Behaviour** - add the property/slot it needs to `vm_clone/qml_backend.py`
   (`@pyqtProperty(..., notify=changed)` for data, `@pyqtSlot(...)` for commands; call
   `self._notify()` after changing state). Reuse the engine - never copy logic.
6. **Check** - `python -m pytest tests/test_qml_ui.py` (loads every screen, fails on any QML warning
   and on a menu key with no handler).

### Port a new colour / size / icon
* Colour, font size, spacing, radius: `ApexTheme/Theme.qml` (mirror of `vm_theme.py`).
* Icon: add a path to `qml/tools/make_icons.py`, run it, use `Icon { name: "myicon" }`.

## What is converted
Main window (menu bar with all seven drop-down menus, both toolbars, tool rail + tool flyout,
flow canvas with draggable cards and wires, Operation Interface, Multi-Flow, image viewer, image strip
with Loop / Run-Stop / load files / load folder, results), start page, and the dialogs: New
Project, Global Variables, Flow Settings, Flow Validation, Module Configuration (4 tabs),
Camera Set, Lens Calibration, Plugin Manager (4 tabs), the Inspection panel (5 tabs) and message
boxes (About, Version, Shortcuts, Manual, ...).

Live behaviour (`appBackend`): open / save / save-as (VMP, JSON, XML), recent projects, templates,
add module, drag-to-move, undo / redo, global variables, flow settings, module parameters,
validation, image pool + folder load, Run / Loop / Stop on a worker thread, role lock,
wire dragging between ports (right-click an input to disconnect), module delete (Del or right-click
menu), canvas pan and zoom (drag, wheel, fit), ROI drawing on the image, and the unsaved-changes
question before a solution is replaced.

## Tool dialogs: live through four services
`vm_clone/qml_services.py` exposes one small QObject per tool dialog (context properties
`appLens`, `appCamera`, `appPlugins`, `appInspection`); each wraps a front-end independent engine:

| dialog | service | engine |
|---|---|---|
| Lens calibration | `LensService` | `core/sessions.py: LensSession` + `apply_lens_calibration` (also used by the widget app) |
| Camera Set | `CameraService` | `core/sessions.py: CameraSession` - threaded live preview, parameters, MVS import / export |
| Plugin Manager | `PluginService` | `sdk/manager.py`, `sdk/marketplace.py` - load / unload / rescan, GitHub + marketplace install on a worker thread, scaffold, package |
| Inspection panel | `InspectionService` | `ui/inspection_controller.py: InspectionController` - dataset load / generate, evaluation with progress and cancel, failures with the box drawn on the image, experiments, compare |

The tool box flyout is built from the live registry (`backend.toolCategories`), so plugin tools
appear in it after a load.

## Still widget-only
The widget lens-calibration dialog now runs on the shared `LensSession` (which also fixed its
view-index bug when a view had no detectable pattern). The widget camera dialog still runs its own
UI-thread preview loop and the widget inspection panel its own worker; both use the same engines
and could be moved onto `CameraSession` / `InspectionService` the same way. Hardware cameras need
the Hikrobot SDK; without it the emulated devices are used.

## Editing in Qt Design Studio
`File > Open Project...` -> `qml/ApexVision.qmlproject`. Components appear in the Library; every
dialog is listed in the Navigator under `DialogHost` (set `current` to its name to preview it).
Design Studio rewrites a file when you edit it visually - it may hard-code a value (for example a
`color:` or a `text:`) in place of a binding. Prefer editing `Theme.qml` for colours, and check
that a changed element still follows its data (e.g. the verdict badge must keep `text: root.verdict`).
