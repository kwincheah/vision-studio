"""Inventory every widget in the running application and report style inconsistencies.

Walks the live widget tree of the main window and each dialog, and for every widget
records its class, object name, rendered size, resolved margins/spacing, font and inline
stylesheet.  Then groups widgets that serve the *same purpose* and reports where they
differ in size, padding, radius or font - which is the material this design-system
standardisation works from.

Run:  python scripts/audit_component_inventory.py
      python scripts/audit_component_inventory.py --json
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "audit")

#: Widget classes that carry a *control* style we care about standardising.
CONTROL_CLASSES = {
    "QPushButton", "QToolButton", "QComboBox", "QLineEdit", "QSpinBox",
    "QDoubleSpinBox", "QCheckBox", "QRadioButton", "QTabBar", "QTabWidget",
    "QTableWidget", "QTreeWidget", "QListWidget", "QHeaderView", "QGroupBox",
    "QLabel", "QStatusBar", "QMenuBar", "QMenu", "QToolBar", "QDockWidget",
    "QProgressBar", "QSlider", "QSplitter", "QScrollArea", "QDialog",
}


def widget_record(w) -> Dict[str, Any]:
    """Everything about one widget that a design system governs."""
    rec: Dict[str, Any] = {
        "class": type(w).__name__,
        "object": w.objectName() or "",
        "size": [w.width(), w.height()],
        "size_hint": [w.sizeHint().width(), w.sizeHint().height()],
        "min_size": [w.minimumWidth(), w.minimumHeight()],
        "max_size": [w.maximumWidth(), w.maximumHeight()],
        "enabled": w.isEnabled(),
        "visible": w.isVisible(),
        "fixed_width": w.minimumWidth() == w.maximumWidth() and w.minimumWidth() > 0,
        "fixed_height": w.minimumHeight() == w.maximumHeight() and w.minimumHeight() > 0,
    }
    try:
        rec["font"] = {
            "family": w.font().family(),
            "size": w.font().pointSize(),
            "weight": int(w.font().weight()),
            "bold": w.font().bold(),
        }
    except Exception:
        pass
    lm = w.layout()
    if lm is not None:
        m = lm.contentsMargins()
        rec["margins"] = [m.left(), m.top(), m.right(), m.bottom()]
        rec["spacing"] = lm.spacing()
    ss = w.styleSheet()
    if ss and ss.strip():
        rec["style_len"] = len(ss)
        rec["style_head"] = " ".join(ss.split())[:150]
    if hasattr(w, "text"):
        try:
            rec["text"] = str(w.text())[:40]
        except Exception:
            pass
    if hasattr(w, "isChecked"):
        try:
            rec["checked"] = w.isChecked()
        except Exception:
            pass
    return rec


def collect(root) -> Dict[str, List[Dict[str, Any]]]:
    from PyQt6.QtWidgets import QWidget

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    try:
        children = root.findChildren(QWidget)
    except RuntimeError:
        return {}          # the dialog was destroyed before it could be inspected
    for w in children:
        try:
            cls = type(w).__name__
            if cls in CONTROL_CLASSES:
                grouped[cls].append(widget_record(w))
        except RuntimeError:
            continue
    if isinstance(root, QWidget) and type(root).__name__ in CONTROL_CLASSES:
        try:
            grouped[type(root).__name__].append(widget_record(root))
        except RuntimeError:
            pass
    return dict(grouped)


def summarise(name: str, records: List[Dict[str, Any]]) -> List[str]:
    """Report the spread of a widget class's sizes and inline styles."""
    lines = []
    sizes = sorted({tuple(r["size"]) for r in records})
    heights = sorted({r["size"][1] for r in records})
    styled = [r for r in records if r.get("style_len")]
    fonts = sorted({(r["font"]["size"], r["font"]["bold"])
                    for r in records if r.get("font")})
    lines.append(f"{name}: {len(records)} instance(s)")
    if len(sizes) > 1:
        shown = ", ".join(f"{w}x{h}" for w, h in sizes[:8])
        lines.append(f"    distinct sizes ({len(sizes)}): {shown}")
    if len(heights) > 1:
        lines.append(f"    distinct heights ({len(heights)}): {heights[:12]}")
    if len(fonts) > 1:
        lines.append(f"    distinct fonts ({len(fonts)}): {fonts[:8]}")
    if styled:
        lines.append(f"    {len(styled)}/{len(records)} carry an inline stylesheet")
        uniq = sorted({" ".join(r["style_head"].split())[:70] for r in styled})
        for s in uniq[:4]:
            lines.append(f"      {s}")
        if len(uniq) > 4:
            lines.append(f"      ... {len(uniq) - 4} more distinct inline styles")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    from PyQt6.QtWidgets import QApplication, QDialog

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(26):
        app.processEvents()

    inventory = {"main_window": collect(win)}

    # Dialogs are separate style contexts and worth measuring on their own.
    from scripts.audit_ui_dialogs import DIALOGS, find_action

    for menu_title, action_text, name in DIALOGS[:9]:
        action = find_action(win, menu_title, action_text)
        if action is None:
            continue
        captured: List[Any] = []

        def on_poll(sink=captured):
            for w in app.topLevelWidgets():
                if isinstance(w, QDialog) and w.isVisible() \
                        and not any(w is c for c in sink):
                    sink.append(w)
                    try:
                        w.close()
                    except Exception:
                        pass

        from PyQt6.QtCore import QTimer
        timer = QTimer()
        timer.setInterval(150)
        timer.timeout.connect(on_poll)
        timer.start()
        try:
            action.trigger()
        except Exception:
            timer.stop()
            continue
        for _ in range(10):
            app.processEvents()
        timer.stop()
        for dlg in captured:
            inventory[f"dialog:{name}"] = collect(dlg)
        for _ in range(4):
            app.processEvents()

    if args.json:
        print(json.dumps(inventory, indent=1, default=str))
        return 0

    # --- cross-context summary -------------------------------------------
    merged: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for context, grouped in inventory.items():
        for cls, records in grouped.items():
            merged[cls].extend(records)

    total = sum(len(v) for v in merged.values())
    print(f"{total} control(s) across {len(merged)} classes "
          f"in {len(inventory)} style context(s)\n")

    with open(os.path.join(OUT, "component_inventory.json"), "w",
              encoding="utf-8") as fh:
        json.dump(inventory, fh, indent=1, default=str)

    # Report the classes with the most inconsistencies first.
    scored = []
    for cls, records in merged.items():
        heights = {r["size"][1] for r in records}
        fonts = {(r["font"]["size"], r["font"]["bold"])
                 for r in records if r.get("font")}
        styles = {r.get("style_head", "")[:60] for r in records if r.get("style_len")}
        score = len(heights) + len(fonts) + len(styles)
        scored.append((score, cls, records, heights, fonts, styles))
    scored.sort(reverse=True, key=lambda t: t[0])

    for score, cls, records, heights, fonts, styles in scored:
        for line in summarise(cls, records):
            print(line)
        print()

    # --- same-purpose, different-style groups ----------------------------
    print("=" * 72)
    print("SAME-PURPOSE GROUPS WITH DIVERGENT STYLING")
    print("=" * 72)
    groups = {
        "text buttons": ["QPushButton"],
        "icon buttons": ["QToolButton"],
        "numeric inputs": ["QSpinBox", "QDoubleSpinBox"],
        "text inputs": ["QLineEdit"],
        "choosers": ["QComboBox"],
        "tables/trees/lists": ["QTableWidget", "QTreeWidget", "QListWidget"],
        "headers": ["QHeaderView"],
        "tabs": ["QTabBar"],
        "section headers": ["QGroupBox"],
    }
    for label, classes in groups.items():
        recs = [r for c in classes for r in merged.get(c, [])]
        if not recs:
            continue
        heights = sorted({r["size"][1] for r in recs})
        fonts = sorted({(r["font"]["size"], r["font"]["bold"])
                        for r in recs if r.get("font")})
        print(f"{label:22s} n={len(recs):3d} heights={heights[:10]} fonts={fonts[:6]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
