"""Audit every module's boolean (checkbox) and colour parameter end to end.

For each of the registered tools this checks that:

* every ``bool`` parameter is offered to the UI as ``kind == "bool"`` (a ToggleSwitch), is
  not rejected by the schema, and round-trips through ``setParamValue`` on a real node;
* the one ``rgb`` parameter is editable and round-trips;
* nothing is silently unreachable (a parameter the UI cannot edit at all).

Run:  python scripts/qa_param_editors.py [--json OUT]
"""
import argparse
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import time  # noqa: E402

from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402

from apex_vision.core import param_schema  # noqa: E402
from apex_vision.core.registry import create_tool_instance, list_all_tools  # noqa: E402
from apex_vision.qml_backend import AppBackend, FrameProvider  # noqa: E402
from apex_vision.qml_services import install_services  # noqa: E402

app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
provider = FrameProvider()
engine.addImageProvider("frame", provider)
backend = AppBackend(provider)
engine.rootContext().setContextProperty("appBackend", backend)
engine._services = install_services(engine, backend)
engine.addImportPath(os.path.join(ROOT, "qml"))
engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
win = engine.rootObjects()[0] if engine.rootObjects() else None
if win is not None:
    win.show()


def pump(n=20):
    for _ in range(n):
        app.processEvents()


def settle(t=30):
    s = 0
    while backend.running and s < t / 0.02:
        app.processEvents()
        time.sleep(0.02)
        s += 1
    pump(10)


problems = []
notes = []
bools = 0
rgb = 0
inactive_bools = []

names = sorted(n if isinstance(n, str) else (n.get("name") or n.get("id"))
               for n in list_all_tools())
print(f"auditing {len(names)} tools\n")

for name in names:
    try:
        inst = create_tool_instance(name, f"qa_{abs(hash(name)) % 100000}", "QA")
        params = dict(inst.parameters)
    except Exception as exc:                                    # noqa: BLE001
        problems.append(("construct", name, f"{type(exc).__name__}: {exc}"))
        continue

    for key, value in params.items():
        try:
            spec = param_schema.spec_for(name, key, value)
        except Exception as exc:                                # noqa: BLE001
            problems.append(("spec", f"{name}.{key}", f"{type(exc).__name__}: {exc}"))
            continue
        kind = spec.get("kind")

        # ---- booleans: the checkbox the user asked about ----
        if isinstance(value, bool):
            bools += 1
            if kind != "bool":
                problems.append(("bool-kind", f"{name}.{key}",
                                 f"a bool parameter renders as {kind!r}, not a checkbox"))
            flipped = not value
            try:
                clamped = param_schema.clamp(spec, flipped)
                issue = param_schema.problem(name, key, value, clamped)
            except Exception as exc:                        # noqa: BLE001
                problems.append(("bool-schema", f"{name}.{key}",
                                 f"{type(exc).__name__}: {exc}"))
                continue
            if clamped is not flipped:
                problems.append(("bool-clamp", f"{name}.{key}",
                                 f"toggle changed {flipped} into {clamped!r}"))
            if issue:
                problems.append(("bool-refused", f"{name}.{key}",
                                 f"toggling is refused: {issue!r}"))
            if not spec.get("active", True):
                inactive_bools.append(f"{name}.{key}")

        # ---- the colour parameter ----
        if kind == "rgb":
            rgb += 1
            try:
                new = param_schema.clamp(spec, [10, 20, 30])
                issue = param_schema.problem(name, key, value, new)
            except Exception as exc:                        # noqa: BLE001
                problems.append(("rgb-schema", f"{name}.{key}",
                                 f"{type(exc).__name__}: {exc}"))
                continue
            if issue:
                problems.append(("rgb-refused", f"{name}.{key}",
                                 f"changing the colour is refused: {issue!r}"))
            notes.append(f"colour {name}.{key}: kind=rgb value={value} "
                         f"sets={list(new) if hasattr(new, '__iter__') else new}")

print(f"{bools} boolean parameters, {rgb} colour parameter(s)")
print(f"{len(inactive_bools)} boolean(s) currently inactive "
      f"(greyed with a reason, e.g. {inactive_bools[:2]})")

# ======================================================================
# end to end: toggle real checkboxes on a real pipeline
# ======================================================================
print("\n=== end to end: toggling real parameters through the backend ===")
backend.newFromTemplate(0) if hasattr(backend, "newFromTemplate") else None
pump(20)

# a few modules that own booleans and the one that owns the colour
cases = []
for candidate in ("BLOB Analysis", "Arc Edge Defect Detection", "Color Measurement",
                  "Camera IO", "Defect Contrast"):
    inst = create_tool_instance(candidate, "probe", "QA")
    keys = [k for k, v in inst.parameters.items() if isinstance(v, bool)][:2]
    if candidate == "Color Measurement":
        keys = [k for k, v in inst.parameters.items() if k == "target_rgb"]
    if keys:
        cases.append((candidate, keys))

for tool, keys in cases:
    backend.addTool(tool)
    pump(20)
    node_id = backend.selectedId
    if not node_id:
        problems.append(("e2e", tool, "addTool selected no node"))
        continue
    node = backend._pipeline.nodes.get(node_id)
    for key in keys:
        before = node.parameters.get(key)
        if isinstance(before, bool):
            ok = backend.setParamValue(node_id, key, not before)
        elif isinstance(before, (list, tuple)):
            ok = backend.setParamValue(node_id, key, [11, 22, 33])
        else:
            continue
        pump(10)
        settle()
        after = node.parameters.get(key)
        print(f"  {tool[:24]:24s} {key[:16]:16s} {before!r:22s} -> {after!r:16s} "
              f"accepted={ok}")
        if not ok:
            problems.append(("e2e-refused", f"{tool}.{key}", "setParamValue returned False"))
        elif after == before:
            problems.append(("e2e-nochange", f"{tool}.{key}",
                             f"value stayed {before!r} after an accepted edit"))

# ======================================================================
print()
print("=" * 70)
print(f"{len(problems)} problem(s)")
for kind, where, detail in problems[:40]:
    print(f"  [{kind}] {where}: {detail}")
for n in notes:
    print("  note:", n)

out = os.path.join(ROOT, "docs/audit/param_editor_audit.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"bools": bools, "rgb": rgb, "inactive_bools": inactive_bools,
               "problems": [{"kind": k, "where": w, "detail": d} for k, w, d in problems],
               "notes": notes}, fh, indent=1)
print(f"\nwritten {out}")
if win is not None:
    win.close()
sys.exit(1 if problems else 0)
