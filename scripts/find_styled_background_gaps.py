"""Find QWidget subclasses with an object name but no WA_StyledBackground.

Qt only paints a stylesheet's `#objectName { background-color: ... }` on a plain
QWidget subclass when the widget sets `WA_StyledBackground`.  Without it the widget
falls back to the global `QWidget` background, which is how the category rail ended
up light and left its light glyphs invisible.

Run:  python scripts/find_styled_background_gaps.py
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    findings = []
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            src = open(path, encoding="utf-8").read()
            lines = src.split("\n")
            # Find every class deriving directly from QWidget.
            for i, line in enumerate(lines):
                m = re.match(r"class\s+(\w+)\((QWidget|QFrame)\)", line)
                if not m:
                    continue
                cls = m.group(1)
                # Look at the class body for setObjectName / the attribute.
                body = "\n".join(lines[i:i + 140])
                end = body.find("\nclass ")
                if end != -1:
                    body = body[:end]
                obj = re.search(r'setObjectName\("([^"]+)"\)', body)
                styled = "WA_StyledBackground" in body
                no_paint = "paintEvent" in body
                # A class that overrides paintEvent paints itself; those are fine.
                if obj and not styled and not no_paint:
                    findings.append((f, i + 1, cls, obj.group(1)))

    if findings:
        print(f"{len(findings)} QWidget subclass(es) with a stylesheet object name "
              f"but no WA_StyledBackground:")
        for f, lineno, cls, obj in findings:
            print(f"  {f}:{lineno}  {cls}  #{obj}")
    else:
        print("no gaps found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
