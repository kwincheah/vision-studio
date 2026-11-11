"""Prove the save-after-run corruption and sweep every registered tool.

Part 1: run a flow, save to a temp file, and inspect what the Image Source now says on disk.
Part 2: instantiate every registered tool, read its parameter schema, and execute it with
        (a) defaults, (b) a hostile value per numeric parameter, recording exceptions.
"""
import glob
import json
import os
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, ".")

from PyQt6.QtCore import QUrl                      # noqa: E402
from PyQt6.QtGui import QGuiApplication            # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine      # noqa: E402

from apex_vision.qml_backend import AppBackend, FrameProvider   # noqa: E402
from apex_vision.qml_services import install_services           # noqa: E402

app = QGuiApplication(sys.argv[:1])
engine = QQmlApplicationEngine()
provider = FrameProvider()
engine.addImageProvider("frame", provider)
backend = AppBackend(provider)
engine.rootContext().setContextProperty("appBackend", backend)
engine._services = install_services(engine, backend)
engine.addImportPath("qml")
engine.load(QUrl.fromLocalFile(os.path.abspath("qml/Main.qml")))
win = engine.rootObjects()[0]
win.show()


def pump(n=30):
    for _ in range(n):
        app.processEvents()


def settle(t=40):
    s = 0
    while backend.running and s < t / 0.02:
        app.processEvents()
        time.sleep(0.02)
        s += 1
    pump(15)


# ======================================================================
print("=" * 72)
print("PART 1: does saving after a run rewrite the project on disk?")
print("=" * 72)
demo = os.path.abspath("projects/PCB_Inspection_Demo.apex")
pump(50)
backend.openRecent(demo)
pump(50)

def source_params(path):
    """.apex is XML; pull the Image Source fields out of the raw text."""
    import re as _re
    text = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    for key in ("source_type", "file_path"):
        m = _re.search(r'<Parameter name="%s"[^>]*>([^<]*)</Parameter>' % key, text)
        out[key] = m.group(1) if m else None
    return out


print("on disk before any run :", source_params(demo))

backend.run()
settle()

out = os.path.abspath("docs/audit/_save_probe.apex")
if os.path.exists(out):
    os.remove(out)
try:
    backend.saveProjectAs(out)
    pump(30)
except Exception as exc:                                        # noqa: BLE001
    print("saveProjectAs raised:", type(exc).__name__, exc)

if os.path.exists(out):
    print("written after the run  :", source_params(out))
    before, after = source_params(demo), source_params(out)
    corrupted = before != after
    print("PROJECT REWRITTEN BY RUNNING:", corrupted)
    if corrupted:
        for k in before:
            if before.get(k) != after.get(k):
                print(f"   {k}: {before.get(k)!r} -> {after.get(k)!r}")
    os.remove(out)
else:
    print("save did not produce a file")

# ======================================================================
print()
print("=" * 72)
print("PART 2: every registered tool - construct, schema, execute")
print("=" * 72)

from apex_vision.core.registry import create_tool_instance, list_all_tools   # noqa: E402
from apex_vision.core.base_tool import ToolStatus                            # noqa: E402

try:
    names = sorted(list_all_tools())
except TypeError:
    names = sorted(list_all_tools([], None))
names = [n if isinstance(n, str) else (n.get("name") or n.get("id")) for n in names]

print(f"{len(names)} tool(s) registered\n")

rows = []
for name in names:
    row = {"tool": name, "construct": "ok", "schema": "ok", "exec_default": "",
           "exec_hostile": "", "notes": ""}
    inst = None
    try:
        inst = create_tool_instance(name, f"qa_{abs(hash(name)) % 10000}", "QA")
        if inst is None:
            row["construct"] = "create_tool_instance returned None"
            rows.append(row)
            continue
    except Exception as exc:                                    # noqa: BLE001
        row["construct"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        continue

    # parameter schema
    try:
        params = inst.get_parameters() if hasattr(inst, "get_parameters") else {}
        if not isinstance(params, dict):
            row["schema"] = f"get_parameters returned {type(params).__name__}"
    except Exception as exc:                                    # noqa: BLE001
        row["schema"] = f"{type(exc).__name__}: {exc}"

    # A tool must never raise: with a missing input it must return an ERROR result.
    # execute() takes a context dict of resolved inputs.
    import numpy as np

    contexts = {
        "empty": {},
        "blank_image": {"Image": np.zeros((240, 320, 3), dtype=np.uint8)},
        "noise_image": {"Image": (np.random.default_rng(0).random((240, 320, 3))
                                  * 255).astype(np.uint8)},
    }
    raised = []
    for label, ctx in contexts.items():
        try:
            result = inst.execute(ctx)
            status = getattr(result, "status", None)
            value = getattr(status, "value", status)
            if label == "blank_image":
                row["exec_default"] = value or "?"
        except Exception as exc:                                # noqa: BLE001
            raised.append(f"{label}:{type(exc).__name__}: {str(exc)[:60]}")
    if raised:
        # noise input is a legitimate input, so only record it if every context raised
        row["exec_hostile"] = raised[0]
        row["notes"] = " | ".join(raised)[:400]
        if len(raised) == len(contexts):
            row["exec_default"] = "RAISED in every context"

    rows.append(row)

broken = [r for r in rows if r["exec_hostile"]
          or r["construct"].startswith(("create", "Type", "Attr", "Key", "Value"))
          or not r["schema"].startswith("ok")]
print(f"{len(broken)} tool(s) with a construct/schema/execute problem\n")
for r in rows:
    flag = "!!" if r in broken else "ok"
    print(f"{flag} {r['tool'][:34]:34s} ctor={r['construct'][:14]:14s} "
          f"exec={r['exec_default'][:22]:22s} {r['notes'][:44]}")

os.makedirs("docs/audit", exist_ok=True)
with open("docs/audit/tool_sweep.json", "w", encoding="utf-8") as fh:
    json.dump(rows, fh, indent=1)
print("\nwritten docs/audit/tool_sweep.json")
win.close()
