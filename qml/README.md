# Apex Vision Studio - QML user interface

A Qt Quick version of the application's main window, start page and New Project dialog,
organised so it can be edited visually in **Qt Design Studio** (or Qt Creator).

## Open it in Qt Design Studio
`File > Open Project...` and choose `qml/ApexVision.qmlproject`. Select `Main.qml`; the
screens render with sample data (`ApexTheme/SampleData.qml`), no Python needed.
Set `startPageVisible` on the root `Window` to preview the start page.

## Layout
| Path | What |
|---|---|
| `ApexVision.qmlproject` | the project file Design Studio opens |
| `Main.qml` | window; start page -> workspace flow |
| `screens/MainScreen.qml` | menu bar, toolbars, tool rail, flow canvas, image viewer, results |
| `screens/StartScreen.qml`, `screens/NewProjectDialog.qml` | start page and its dialog |
| `ApexTheme/Theme.qml` | every colour, font size, spacing and radius (the design tokens) |
| `ApexTheme/SampleData.qml` | design-time sample data |
| `ApexDialogs/` | every dialog + `DialogHost.qml` |
| `ApexComponents/` | reusable parts: `AppButton`, `Chip`, `ChromeToolButton`, `TextBox`, `SelectBox`, `ToggleSwitch`, `StatusBadge`, `TelemetryChip`, `NodeCard`, `PortDot`, `TabButton2`, `FormRow`, `Icon`, `DialogFrame`, `DataTable`, `CheckLabel`, `NumberBox`, `SectionLabel`, `DropMenu` |
| `images/` | SVG icons (`light` on dark chrome, `dark` on panels, `accent`, `white`) and a sample image |
| `tools/make_icons.py` | regenerates the icon set |

Change a value in `Theme.qml` and every component follows. To add an icon, add it to
`tools/make_icons.py` and re-run it.

## Run it against the real engine
```
python qml_main.py [solution.vmp | solution.xml]
```
`apex_vision/qml_backend.py` exposes the loaded solution to QML as `appBackend`: modules,
wiring, layout, verdicts, timings, the current image, recent projects, and the commands
`run`, `stop`, `saveProject`, `moveNode`, `openRecent`, `createProject`, ... Flows run on a
worker thread. Every screen uses `typeof appBackend !== "undefined"` to fall back to sample
data, which is what keeps the design canvas working.

## Status
Every screen and dialog of the widget application has a live QML counterpart. Editing, running,
saving, images, wiring, ROI, lens calibration, camera preview, plugins and the inspection
evaluation all run on the real engine; see `docs/QML_CONVERSION.md` for the mapping, the services
(`apex_vision/qml_services.py`) and the recipe for porting more.
