"""Find which widget's inline stylesheet Qt cannot parse.

A "Could not parse stylesheet of object ..." warning means Qt discarded the *whole*
inline stylesheet for that widget, so the widget renders unthemed.  It is easy to miss
because Qt only writes it to stderr, so this walks the live widget tree and asks Qt to
parse each widget's own stylesheet.

Run:  python scripts/find_bad_stylesheets.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def main() -> int:
    from PyQt6.QtWidgets import QApplication, QWidget, QMessageBox, QDialog, QLabel

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.resize(1400, 760)
    win.show()
    for _ in range(20):
        app.processEvents()

    bad = []
    checked = 0
    for w in win.findChildren(QWidget):
        css = w.styleSheet()
        if not css or not css.strip():
            continue
        checked += 1
        # Ask Qt to actually parse it.  setStyleSheet is what emits the warning; a
        # re-set of the same string on a scratch widget reproduces it deterministically.
        scratch = QLabel()
        try:
            scratch.setStyleSheet(css)
        except Exception as exc:
            bad.append((type(w).__name__, w.objectName(), str(exc)[:80], css[:120]))
            continue
        finally:
            scratch.deleteLater()

    print(f"checked {checked} widget(s) carrying an inline stylesheet")
    if bad:
        print(f"\n{len(bad)} could not be parsed:")
        for cls, obj, err, css in bad:
            print(f"  {cls}({obj}) {err}")
            print(f"      {css!r}")
    else:
        print("all inline stylesheets parsed cleanly")

    # Also check the two global sheets for brace balance, which is the usual cause.
    from vm_clone.ui.styles import INDUSTRIAL_THEME_QSS
    from vm_clone.ui.vm_theme import VM_THEME_QSS
    for name, css in (("INDUSTRIAL_THEME_QSS", INDUSTRIAL_THEME_QSS),
                      ("VM_THEME_QSS", VM_THEME_QSS)):
        print(f"\n{name}: {css.count('{')} open / {css.count('}')} close  "
              f"len={len(css)}")
        # find the first rule whose braces do not balance
        depth = 0
        line = 1
        for ch in css:
            if ch == "\n":
                line += 1
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    print(f"  unbalanced '}}' at line {line}")
                    break
        if depth > 0:
            print(f"  {depth} unclosed rule(s) at end of sheet")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
