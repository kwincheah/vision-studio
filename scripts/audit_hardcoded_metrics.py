"""Find hardcoded visual constants in the UI code.

A design system only holds if every dimension comes from one place.  This lists the
literal pixel heights, widths, font sizes and radii scattered through the UI modules,
grouped by property, so the outliers that break a component family are visible before
anything is changed.

Run:  python scripts/audit_hardcoded_metrics.py
"""
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UI_DIR = os.path.join(ROOT, "vm_clone", "ui")

#: property -> regex capturing the numeric value
PATTERNS: Dict[str, str] = {
    "setFixedHeight": r"setFixedHeight\((\d+)\)",
    "setFixedWidth": r"setFixedWidth\((\d+)\)",
    "setFixedSize(w,h)": r"setFixedSize\((\d+),\s*(\d+)\)",
    "setMinimumHeight": r"setMinimumHeight\((\d+)\)",
    "setMinimumWidth": r"setMinimumWidth\((\d+)\)",
    "setMaximumHeight": r"setMaximumHeight\((\d+)\)",
    "setIconSize": r"setIconSize\(QSize\((\d+),\s*(\d+)\)\)",
    "QSize(w,h)": r"QSize\((\d+),\s*(\d+)\)",
    "font-size:Npx": r"font-size:\s*(\d+)px",
    "font-size:Npt": r"font-size:\s*(\d+)pt",
    "border-radius:Npx": r"border-radius:\s*(\d+)px",
    "padding:Npx": r"padding:\s*(\d+)px",
    "setSpacing": r"setSpacing\((\d+)\)",
    "setContentsMargins": r"setContentsMargins\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)",
    "setPointSize": r"setPointSize\((\d+)\)",
    "QFont(size)": r"QFont\([^,)]+,\s*(\d+)",
}

#: which files are UI code (styles.py/vm_theme.py are the design system itself)
SKIP = {"styles.py", "vm_theme.py"}


def main() -> int:
    findings: Dict[str, List[Tuple[str, int, str]]] = defaultdict(list)
    for fname in sorted(os.listdir(UI_DIR)):
        if not fname.endswith(".py") or fname in SKIP:
            continue
        path = os.path.join(UI_DIR, fname)
        for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
            for prop, pattern in PATTERNS.items():
                for m in re.finditer(pattern, line):
                    values = "/".join(m.groups())
                    findings[prop].append((fname, lineno, values))

    total = sum(len(v) for v in findings.values())
    print(f"{total} hardcoded visual constant(s) across "
          f"{len(findings)} propert(ies) in vm_clone/ui "
          f"(excluding the design-system modules)\n")

    for prop in sorted(findings, key=lambda p: -len(findings[p])):
        items = findings[prop]
        values = sorted({v for _, _, v in items},
                        key=lambda s: (len(s), s))
        print(f"{prop:22s} n={len(items):3d}  distinct={len(values)}")
        print(f"    values: {', '.join(values[:16])}")
        by_file: Dict[str, int] = defaultdict(int)
        for f, _, _ in items:
            by_file[f] += 1
        top = sorted(by_file.items(), key=lambda kv: -kv[1])[:5]
        print(f"    files : {', '.join(f'{f}({n})' for f, n in top)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
