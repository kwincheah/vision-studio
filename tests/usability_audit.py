"""Measured usability audit of the QML window (run directly: python tests/usability_audit.py)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from PyQt6.QtCore import QPointF, Qt
from test_qml_interaction import Ui

def lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def _no_wrap(it):
    try:
        return it.property("wrapMode") == 0
    except TypeError:                      # enum not convertible: assume wrapping text
        return False


def _backdrop(it):
    p = it.parentItem()
    while p is not None:
        c = p.property("color") if p.property("radius") is not None else None     # a Rectangle (or a component built on one)
        if c is not None and hasattr(c, "alpha"):
            if c.alpha() >= 250 and p.property("visible"):
                return (c.red(), c.green(), c.blue())
        p = p.parentItem()
    return None


def _in_table(it):
    p = it.parentItem()
    while p is not None:
        if p.metaObject().className().startswith("DataTable"):
            return True
        p = p.parentItem()
    return False


def audit(ui, label, root=None):
    ui.spin(25)
    img = ui.w.grabWindow()
    sx = img.width() / max(1, ui.w.width())            # device pixels per logical pixel
    out = {"small_targets": [], "small_text": [], "low_contrast": [], "truncated": [], "overflow": []}
    for it in (ui.walk(root) if root is not None else ui.walk()):
        if not it.isVisible() or it.width() <= 0 or it.height() <= 0:
            continue
        cls = it.metaObject().className()
        p = it.mapToScene(QPointF(0, 0))
        if p.x() < 0 or p.y() < 0 or p.x() > img.width() or p.y() > img.height():
            continue
        if cls.startswith("QQuickMouseArea"):
            par = it.parentItem()
            w, h = it.width(), it.height()
            if (w < 24 or h < 22) and it.property("enabled"):
                pp = par.mapToScene(QPointF(0, 0))
                out["small_targets"].append((cls, round(w), round(h), int(pp.x()), int(pp.y()), par.metaObject().className()))
        if cls.startswith("QQuickText") and (it.property("text") or "").strip():
            fs = it.property("font").pixelSize()
            txt = it.property("text")
            if 0 < fs < 11:
                out["small_text"].append((txt[:30], fs))
            # contrast of the text colour against the nearest opaque rectangle behind it (token based,
            # so it does not depend on fonts or the Qt platform plugin)
            col = it.property("color")
            fg = (col.red(), col.green(), col.blue())
            bg = _backdrop(it)
            if bg is not None:
                r = ratio(fg, bg)
                need = 3.0 if fs >= 18 else 4.5
                if r < need:
                    out["low_contrast"].append((txt[:30], round(r, 2), fs))
            if it.property("truncated") and not _in_table(it):          # table cells show the full text on hover
                out["truncated"].append(txt[:40])
            elif it.property("contentWidth") > it.width() + 1 and it.width() > 0 and _no_wrap(it):
                out["overflow"].append((txt[:40], round(it.property("contentWidth")), round(it.width())))
    return out

if __name__ == "__main__":
    ui = Ui()
    res = {}
    ui.settle()
    res["main"] = audit(ui, "main")
    for tab in (1, 2):
        ui.main.setProperty("workspaceTab", tab); ui.spin(30)
        res[f"tab{tab}"] = audit(ui, f"tab{tab}")
    ui.main.setProperty("workspaceTab", 0)
    from test_qml_sweep import MENU, open_menu
    want = {"globalVars", "flowSettings", "validate", "cameraSet", "lensCal", "newSolution", "plugins", "about", "manual"}
    for title, text, key in MENU:
        if key not in want:
            continue
        open_menu(ui, title); ui.click_text(text); ui.spin(40)
        frames = [f for f in ui.host.childItems() if f.isVisible() and f.width() > 100]
        if not frames:
            print("no dialog for", key); continue
        res["dlg_" + key] = audit(ui, key, frames[0])
        ui.close_dialog()
    json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else "audit.json", "w"), indent=1, default=str)
    for k, v in res.items():
        print("==", k, {a: len(b) for a, b in v.items()})
