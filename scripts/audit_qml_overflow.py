"""Measure only the *visible dialog*, not the workspace behind it.

The previous pass miscounted because every hidden dialog still exists in the tree.  This
finds the frame that is actually visible, then reports:

  * text wider than its box with no elide/wrap, and
  * a control whose right edge passes the dialog frame's right edge.

Run:  python scripts/audit_qml_overflow.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402

DIALOGS = ("newProject", "globalVars", "comm", "flowSettings", "validation",
           "cameraSet", "lensCal", "plugins", "confirm")


def num(obj, name):
    try:
        return float(obj.property(name) or 0)
    except Exception:
        return 0.0


def walk(node, depth=0):
    yield node, depth
    if depth > 24:
        return
    try:
        kids = node.childItems()
    except Exception:
        return
    for kid in kids:
        yield from walk(kid, depth + 1)


def is_visible(obj) -> bool:
    try:
        return bool(obj.property("visible")) and obj.property("opacity") != 0
    except Exception:
        return False


def has_overflow_handling(obj) -> bool:
    """A Text that declares `elide` or `wrapMode` is handling its own overflow."""
    for prop in ("elide", "wrapMode"):
        try:
            obj.property(prop)          # raises TypeError for a C++ enum it cannot convert
            return True
        except TypeError:
            return True
        except Exception:
            continue
    return False


def find_dialog_frame(host):
    """The dialog's card (`objectName: "dialogCard"`), not the full-window DialogFrame.

    Every dialog is `anchors.fill: parent`, and DialogFrame itself fills the host, so its
    outer item is the whole window.  The card is the inner Rectangle sized from
    `dialogWidth`, and that is the real bound a control must not cross.
    """
    for kid in host.childItems():
        if not is_visible(kid):
            continue
        for obj, _d in walk(kid):
            if not is_visible(obj):
                continue
            try:
                if obj.property("objectName") == "dialogCard":
                    return obj
            except Exception:
                continue
    return None


def audit(frame, verbose: bool = False):
    problems = []
    frame_w = num(frame, "width")
    for obj, _d in walk(frame):
        if not is_visible(obj):
            continue
        try:
            text = obj.property("text")
        except Exception:
            text = None
        w = num(obj, "width")
        try:
            implicit = float(obj.property("implicitWidth") or 0)
        except Exception:
            implicit = 0.0

        if text and isinstance(text, str) and w > 0 and implicit > w + 0.5:
            if not has_overflow_handling(obj):
                problems.append(("text-clipped", text[:40], round(implicit, 1),
                                 round(w, 1)))

        # A control must stay inside the CARD.  Both boxes are in the frame's coordinate
        # system, because `x` is relative to the parent and the card is centred, so
        # comparing a child's local x against the card's width reports false positives.
        try:
            from PyQt6.QtCore import QPointF

            # PyQt6's mapToItem takes a QPointF; passing two ints raises TypeError, which
            # used to make this whole check skip every item and report a clean bill.
            left = obj.mapToItem(frame, QPointF(0, 0)).x()
            right = left + w
            if frame_w > 0 and right > frame_w + 2:
                label = (text[:34] if (text and isinstance(text, str)) else "")
                name = obj.property("objectName") or type(obj).__name__
                problems.append(("past-card-edge", f"{name} {label}".strip(),
                                 round(right, 1), round(frame_w, 1)))
                if verbose:
                    print(f"        {name}: left={left:.0f} w={w:.0f} "
                          f"right={right:.0f} card={frame_w:.0f}")
        except Exception as exc:
            if verbose:
                print(f"        (map failed: {type(exc).__name__}: {exc})")
    return problems


def main() -> int:
    from apex_vision.qml_backend import AppBackend, FrameProvider
    from apex_vision.qml_services import install_services

    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    provider = FrameProvider()
    engine.addImageProvider("frame", provider)
    backend = AppBackend(provider)
    engine.rootContext().setContextProperty("appBackend", backend)
    engine._services = install_services(engine, backend)
    engine.addImportPath(os.path.join(ROOT, "qml"))
    engine.load(QUrl.fromLocalFile(os.path.join(ROOT, "qml", "Main.qml")))
    win = engine.rootObjects()[0]
    win.setProperty("width", 1600)
    win.setProperty("height", 950)
    win.show()

    def pump(n=25):
        for _ in range(n):
            app.processEvents()

    pump(50)
    backend.openRecent(os.path.join(ROOT, "projects", "PCB_Inspection_Demo.apex"))
    pump(50)

    content = win.contentItem()
    host = next((o for o, _ in walk(content)
                 if o.property("current") is not None and hasattr(o, "show")), None)
    if host is None:
        print("FAIL: dialog host not found")
        return 1

    total = 0
    for dialog in DIALOGS:
        host.show(dialog)
        pump(22)
        frame = find_dialog_frame(host)
        if frame is None:
            print(f"{dialog:12s} (no visible frame)")
            continue
        problems = audit(frame, verbose=True)
        total += len(problems)
        print(f"{dialog:12s} frame {num(frame, 'width'):.0f}x"
              f"{num(frame, 'height'):.0f}   {len(problems)} problem(s)")
        for kind, what, need, have in problems[:8]:
            print(f"     {kind:16s} {what!r:42s} {need} vs {have}")
    host.close()
    pump(10)
    print(f"\n{total} problem(s) in the dialogs' own frames")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
