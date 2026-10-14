"""Snap the remaining inline padding values in the UI modules onto the spacing scale.

The token pass covers the two stylesheet modules; individual screens carry their own
inline stylesheets for bespoke composition, and eight of their padding values were
off-scale (`7px`, `10px`, `14px`, `18px`, `1px 7px`).  Each component is snapped to the
nearest step with ties rounded up, so a control is never tighter than the scale intends.

Run:  python scripts/snap_inline_spacing.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

UI_DIR = os.path.join(ROOT, "vm_clone", "ui")
SKIP = {"styles.py", "vm_theme.py"}

#: properties whose components are snapped, and the token prefix for each
PROPS = {"padding": "sp", "margin": "sp", "border-radius": "r"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from vm_clone.ui.styles import RADIUS, SPACE

    tables = {"sp": SPACE, "r": RADIUS}

    def snap(prefix: str, px: int) -> str:
        table = tables[prefix]
        name = min(table, key=lambda k: (abs(table[k] - px), -table[k]))
        return name

    total = 0
    for fname in sorted(os.listdir(UI_DIR)):
        if not fname.endswith(".py") or fname in SKIP:
            continue
        path = os.path.join(UI_DIR, fname)
        src = open(path, encoding="utf-8").read()
        changed = 0

        for prop, prefix in PROPS.items():
            pattern = re.compile(rf"(\b{prop}\s*:\s*)([^;{{}}]+)(;)")

            def repl(m):
                nonlocal changed
                raw = m.group(2).strip()
                if "{" in raw or not re.fullmatch(r"[\d px]+", raw):
                    return m.group(0)
                parts = raw.split()
                out = []
                dirty = False
                table = tables[prefix]
                for part in parts:
                    mm = re.fullmatch(r"(\d+)px", part)
                    if not mm:
                        out.append(part)
                        continue
                    px = int(mm.group(1))
                    if px in table.values():
                        out.append(part)
                        continue
                    name = min(table, key=lambda k: (abs(table[k] - px), -table[k]))
                    out.append(f"{{THEME['{prefix}_{name}']}}px")
                    dirty = True
                if not dirty:
                    return m.group(0)
                changed += 1
                return f"{m.group(1)}{' '.join(out)}{m.group(3)}"

            src = pattern.sub(repl, src)

        if changed:
            total += changed
            print(f"  {fname}: {changed} declaration(s)")
            if args.apply:
                open(path, "w", encoding="utf-8").write(src)

    print(f"\n{total} inline declaration(s) snapped onto the scale")
    return 0


if __name__ == "__main__":
    sys.exit(main())
