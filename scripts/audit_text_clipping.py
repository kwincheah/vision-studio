"""Check for clipped text in the flow telemetry strip and status bar.

A label whose rendered width is smaller than its text needs is clipped, and the audit
found exactly that class of defect earlier ("Ru" instead of "Run all").  This measures
every visible label's required width against the width it was actually given.

Run:  python scripts/audit_text_clipping.py
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main() -> int:
    from PyQt6.QtGui import QFontMetrics
    from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QComboBox, QAbstractButton

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication([])
    initialize_app_fonts(app)
    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(28):
        app.processEvents()

    # run the flow so the telemetry labels carry real values
    win.run_pipeline_step()
    for _ in range(10):
        app.processEvents()

    clipped = []
    tight = []
    for w in win.findChildren((QLabel, QPushButton, QComboBox, QAbstractButton)):
        if not w.isVisible():
            continue
        text = ""
        if isinstance(w, QComboBox):
            text = w.currentText()
        elif hasattr(w, "text"):
            try:
                text = w.text()
            except Exception:
                continue
        if not text:
            continue
        # A rich-text label returns its raw markup from `text()`, so measuring that with
        # QFontMetrics counts the tags as glyphs and reports a false clip.  Only the
        # text Qt actually draws is measured.
        if "<" in text and ">" in text:
            import html

            text = html.unescape(re.sub(r"<br\s*/?>", " ", text, flags=re.I))
            text = re.sub(r"<[^>]+>", "", text).replace("\xa0", " ").strip()
            if not text:
                continue
        fm = QFontMetrics(w.font())
        # an icon consumes its width plus the button's spacing
        icon_w = 0
        if hasattr(w, "icon") and not w.icon().isNull():
            icon_w = w.iconSize().width() + 6
        needed = fm.horizontalAdvance(text) + icon_w
        # subtract the frame/padding the stylesheet adds
        inner = w.width() - 12
        if needed > inner:
            entry = (type(w).__name__, w.objectName() or "-", text[:26],
                     needed, w.width())
            if needed > w.width():
                clipped.append(entry)
            else:
                tight.append(entry)

    print(f"{len(clipped)} clipped, {len(tight)} tight\n")
    if clipped:
        print("CLIPPED (text needs more than the widget's whole width):")
        for cls, obj, text, need, got in clipped:
            print(f"   {cls:12s} {obj:18s} {text!r:28s} needs {need:4d}px, has {got:4d}px")
    if tight:
        print("\nTIGHT (fits, but with under 12px of slack):")
        for cls, obj, text, need, got in tight:
            print(f"   {cls:12s} {obj:18s} {text!r:28s} needs {need:4d}px, has {got:4d}px")
    return 1 if clipped else 0


if __name__ == "__main__":
    sys.exit(main())
