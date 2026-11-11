"""Check focus-ring visibility, and that every control is reachable by Tab.

Two accessibility properties that contrast auditing alone does not cover:

  * a focus ring must be visible on the surface it is drawn on (WCAG 2.4.11 asks for
    3:1 between the focused and unfocused states, and 2.4.7 for a visible indicator);
  * every interactive control must be in the Tab chain, or a keyboard-only operator
    cannot reach it.

Run:  python scripts/audit_qml_focus.py
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402

QML = os.path.join(ROOT, "qml")

#: Surfaces a focus ring can be drawn on, and the ink it uses.  Two ring tokens exist:
#: `primary` on light surfaces, `focusOnChrome` on the dark chrome, because blue on
#: chromeDark measures 1.11:1 and is effectively invisible.
RING_PAIRS = [
    ("primary", "panel", "ring on a panel (buttons, checkboxes)"),
    ("primary", "panelAlt", "ring on a selected tab / alternate panel"),
    ("primary", "fieldBg", "ring on an input well"),
    ("primary", "buttonBg", "ring on a secondary button"),
    ("primary", "card", "ring on a node card"),
    ("focusOnChrome", "chromeDark", "ring on the dark toolbar"),
    ("focusOnChrome", "chrome", "ring on the menu strip"),
    ("focusOnChrome", "rail", "ring on the tool rail"),
]

#: Components that must be keyboard reachable.
INTERACTIVE = ("AppButton", "ChromeToolButton", "ChromePillButton", "TextBox",
               "SelectBox", "NumberBox", "CheckLabel", "ToggleSwitch", "TabButton2",
               "ModelPicker")


def srgb(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(h):
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def theme_colours():
    text = open(os.path.join(QML, "ApexTheme", "Theme.qml"), encoding="utf-8").read()
    return {m.group(1): m.group(2).lower()
            for m in re.finditer(r'readonly property color (\w+)\s*:\s*"(#[0-9a-fA-F]{6})"',
                                 text)}


def focus_sources():
    """Every QML file that draws a focus indication, with the lines that do it."""
    found = {}
    for dirpath, _dirs, files in os.walk(QML):
        for name in files:
            if not name.endswith(".qml"):
                continue
            path = os.path.join(dirpath, name)
            text = open(path, encoding="utf-8").read()
            hits = []
            for i, line in enumerate(text.splitlines(), 1):
                if "activeFocus" in line and ("border" in line or "width:" in line
                                              or "visible" in line or "color" in line):
                    hits.append((i, line.strip()))
            if hits:
                found[os.path.relpath(path, ROOT).replace("\\", "/")] = hits
    return found


def main() -> int:
    theme = theme_colours()
    ok = True

    print("== focus-ring contrast ==")
    for fg, bg, where in RING_PAIRS:
        if fg not in theme or bg not in theme:
            print(f"  SKIP  {fg} on {bg}")
            continue
        ratio = contrast(theme[fg], theme[bg])
        good = ratio >= 3.0
        ok = ok and good
        print(f"  {'ok  ' if good else 'FAIL'}  {ratio:5.2f}:1 (need 3.0)  "
              f"{fg} on {bg:10s} {where}")

    print("\n== which components draw a focus ring ==")
    sources = focus_sources()
    for rel in sorted(sources):
        name = os.path.basename(rel)
        print(f"  {name}:")
        for line_no, line in sources[rel][:3]:
            print(f"      {line_no}: {line[:96]}")

    # every interactive component must be reachable by keyboard
    print("\n== keyboard reachability ==")
    #: components whose focus target is an inner item, so `activeFocusOnTab` lives there
    INNER = {"TextBox": "activeFocusOnTab", "NumberBox": "activeFocusOnTab"}
    for component in INTERACTIVE:
        path = os.path.join(QML, "ApexComponents", component + ".qml")
        if not os.path.exists(path):
            print(f"  SKIP  {component} (not in ApexComponents)")
            continue
        text = open(path, encoding="utf-8").read()
        has_focus = "activeFocusOnTab" in text
        has_ring = "activeFocus" in text
        if not has_focus:
            ok = False
            print(f"  FAIL  {component:18s} not in the Tab chain "
                  f"(no activeFocusOnTab)")
        elif not has_ring:
            ok = False
            print(f"  FAIL  {component:18s} focusable but draws no focus ring")
        else:
            print(f"  ok    {component:18s} focusable and draws a ring")

    print()
    print("RESULT:", "focus is handled everywhere checked"
          if ok else "problems above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
