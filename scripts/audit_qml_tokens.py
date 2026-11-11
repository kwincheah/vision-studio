"""Find colour literals in QML that bypass `Theme.qml`.

A design system only holds if every surface takes its colour from one place.  QML has no
stylesheet cascade to enforce that, so a literal `"#22c55e"` in a component silently
becomes a second source of truth - it drifts when the palette changes, and it is invisible
to any contrast or audit pass.

Run:  python scripts/audit_qml_tokens.py
"""
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QML = os.path.join(ROOT, "qml")
THEME = os.path.join(QML, "ApexTheme", "Theme.qml")

HEX = re.compile(r'"#[0-9a-fA-F]{6}"')
#: literals that are legitimately not palette entries
ALLOW = {
    "qml/ApexTheme/SampleData.qml",     # demo data, not styling
}
#: colours used only for drawing overlays onto an image, where a palette token would be
#: wrong (these are pixel colours for the picture, not for the interface)
OVERLAY_HINT = ("overlay", "annotation", "wire", "roi", "heat", "mask")


def theme_tokens() -> dict:
    text = open(THEME, encoding="utf-8").read()
    return {m.group(2).lower(): m.group(1)
            for m in re.finditer(r'readonly property color (\w+)\s*:\s*"(#[0-9a-fA-F]{6})"',
                                 text)}


def main() -> int:
    tokens = theme_tokens()
    by_value = defaultdict(list)
    for name, value in tokens.items():
        by_value[value].append(name)

    findings = []
    total_literals = 0
    for dirpath, _dirs, files in os.walk(QML):
        for name in sorted(files):
            if not name.endswith(".qml"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            if rel in ALLOW or rel == "qml/ApexTheme/Theme.qml":
                continue
            text = open(path, encoding="utf-8").read()
            for m in HEX.finditer(text):
                total_literals += 1
                value = m.group(0).strip('"').lower()
                line = text[:m.start()].count("\n") + 1
                context = text.splitlines()[line - 1].strip()
                findings.append({
                    "file": rel, "line": line, "value": value,
                    "token": (by_value.get(value) or [None])[0],
                    "context": context[:90],
                })

    print(f"{total_literals} colour literal(s) outside Theme.qml\n")

    duplicates = [f for f in findings if f["token"]]
    novel = [f for f in findings if not f["token"]]

    print(f"== {len(duplicates)} literal(s) that duplicate an existing token ==")
    per_file = Counter(f["file"] for f in duplicates)
    for rel, n in per_file.most_common():
        print(f"  {n:3d}  {rel}")
    print()
    for f in duplicates[:12]:
        print(f"  {f['file']}:{f['line']:<5} {f['value']}  == Theme.{f['token']}")

    print(f"\n== {len(novel)} literal(s) with no token at all ==")
    per_value = Counter(f["value"] for f in novel)
    for value, n in per_value.most_common():
        files = sorted({f["file"] for f in novel if f["value"] == value})
        print(f"  {value}  x{n:<3}  {', '.join(files[:3])}"
              f"{' ...' if len(files) > 3 else ''}")
    return 1 if (duplicates or novel) else 0


if __name__ == "__main__":
    sys.exit(main())
