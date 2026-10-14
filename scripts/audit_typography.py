"""Report the actual rendered font of representative widgets.

Qt keeps two independent font channels: the application font set with
`QApplication.setFont`, and the `font-size` declared in a stylesheet.  Where they
disagree, a widget's rendered size depends on whether it resolved through the
stylesheet or through the inherited font, which is invisible in the source and shows up
as inconsistent text sizing between panels.  This measures the resolved result.

Run:  python scripts/audit_typography.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main() -> int:
    from PyQt6.QtWidgets import (QApplication, QLabel, QPushButton, QLineEdit,
                                 QComboBox, QSpinBox, QCheckBox)

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication([])
    initialize_app_fonts(app)
    print("QApplication.setFont ->", app.font().family(), app.font().pointSize(), "pt",
          f"({app.font().pixelSize()} px pixel-size)")

    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(24):
        app.processEvents()

    from PyQt6.QtGui import QFontMetrics

    def describe(label, w):
        f = w.font()
        fm = QFontMetrics(f)
        print(f"  {label:34s} {f.family():14s} {f.pointSize():>3}pt "
              f"bold={str(f.bold()):5s} weight={int(f.weight()):3d} "
              f"height={fm.height():2d}px cap={fm.capHeight():2d}px")

    print("\nwidgets that resolve their font from the application font:")
    seen = set()
    for cls in (QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox):
        for w in win.findChildren(cls):
            if not w.isVisible():
                continue
            key = (cls.__name__, w.font().pointSize(), w.font().bold())
            if key in seen:
                continue
            seen.add(key)
            name = w.objectName() or (w.text()[:20] if hasattr(w, "text") else "")
            describe(f"{cls.__name__}({name})", w)

    # Compare a wizard label against a status-bar label and a module label.
    print("\nsame-purpose comparison across panels:")
    pairs = [
        ("status bar", win.lbl_view_status),
        ("module log", getattr(win, "lbl_component_state", None)),
    ]
    for label, w in pairs:
        if w is not None:
            describe(label, w)

    labels = [w for w in win.findChildren(QLabel) if w.isVisible() and w.text()]
    sizes = {}
    for w in labels:
        sizes.setdefault(w.font().pointSize(), []).append(w.text()[:18])
    print("\nQLabel point sizes actually in use:")
    for size in sorted(sizes, reverse=True):
        items = sizes[size]
        print(f"  {size}pt  x{len(items):3d}  e.g. {items[:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
