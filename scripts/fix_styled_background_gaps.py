"""Set `WA_StyledBackground` on QWidget subclasses that use a stylesheet background.

Qt only paints a stylesheet's `#objectName { background-color: ... }` on a plain
QWidget subclass when the widget sets `WA_StyledBackground`.  Without it the widget
falls back to the global `QWidget` background - which is how the category rail ended
up light and left its light glyphs invisible.

Only classes whose object name actually has a background rule are touched, so this
cannot change a widget that has no background to paint.

Run:  python scripts/fix_styled_background_gaps.py --check
      python scripts/fix_styled_background_gaps.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.vm_theme import VM_THEME_QSS  # noqa: E402

ATTR = ("        # A QWidget subclass does not paint its `#objectName` background from\n"
        "        # the stylesheet unless it is told to; without this it falls back to\n"
        "        # the global light `QWidget` background.\n"
        "        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)\n")


def has_background_rule(obj: str) -> bool:
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", VM_THEME_QSS, re.S):
        sel = m.group(1)
        if f"#{obj}" in sel and "background" in m.group(2):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    for root, _d, files in os.walk(os.path.join(ROOT, "vm_clone")):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            lines = open(path, encoding="utf-8").read().split("\n")
            changed = 0
            for i, line in enumerate(lines):
                m = re.match(r"class\s+(\w+)\((QWidget|QFrame)\)", line)
                if not m:
                    continue
                body = "\n".join(lines[i:i + 140])
                end = body.find("\nclass ")
                if end != -1:
                    body = body[:end]
                if "WA_StyledBackground" in body or "paintEvent" in body:
                    continue
                om = re.search(r'( +)self\.setObjectName\("([^"]+)"\)', body)
                if not om:
                    continue
                if not has_background_rule(om.group(2)):
                    continue
                # Insert right after the setObjectName line.
                for j in range(i, min(len(lines), i + 140)):
                    if 'setObjectName("' + om.group(2) + '")' in lines[j]:
                        indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                        block = ATTR.replace("        ", indent)
                        lines[j + 1:j + 1] = block.rstrip("\n").split("\n")
                        changed += 1
                        break
            if changed:
                total += changed
                print(f"  {f}: {changed} class(es)")
                if args.apply:
                    open(path, "w", encoding="utf-8").write("\n".join(lines))

    print(f"\n{total} widget class(es) given WA_StyledBackground")
    return 0


if __name__ == "__main__":
    sys.exit(main())
