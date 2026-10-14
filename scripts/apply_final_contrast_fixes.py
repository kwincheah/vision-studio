"""Apply the final contrast corrections to the theme stylesheet.

`retint_ui.py` maps the *dark* originals onto the light palette, but three rules were
written after that mapping and use a fixed light ink that the retint flips back to the
body ink.  This re-asserts them, so the theme is reproducible after a restore.

Run:  python scripts/apply_final_contrast_fixes.py --apply
"""
import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "vm_theme.py")

EDITS = [
    # A saturated green fill needs white ink; the body ink measures 3.28:1 on it.
    (
        "stripPlayButton ink",
        """QPushButton#stripPlayButton, QToolButton#stripPlayButton {{
    background-color: #15803d;
    color: {T['text_primary']};""",
        """QPushButton#stripPlayButton, QToolButton#stripPlayButton {{
    background-color: #15803d;
    color: #ffffff;""",
    ),
    # Status labels must declare a transparent background, or Qt paints the strip with
    # the label's own background and hides the chrome.
    (
        "status label backgrounds",
        """QLabel#statusSegment {{
    color: {T['text_on_chrome']};""",
        """QLabel#statusSegment {{
    background: transparent;
    color: {T['text_on_chrome']};""",
    ),
    (
        "status leading background",
        """QLabel#statusLeading {{
    color: {T['text_on_chrome']};""",
        """QLabel#statusLeading {{
    background: transparent;
    color: {T['text_on_chrome']};""",
    ),
    (
        "status message background",
        """QLabel#statusMessage {{
    color: {T['text_on_chrome']};""",
        """QLabel#statusMessage {{
    background: transparent;
    color: {T['text_on_chrome']};""",
    ),
    (
        "selection edge on tree rows",
        """QTreeWidget::item:selected {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['vm_accent']};""",
        """QTreeWidget::item:selected {{
    background-color: {T['vm_accent_dim']};
    border-color: {T['accent_border']};""",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    applied, skipped = 0, []
    for label, old, new in EDITS:
        if old in src:
            src = src.replace(old, new, 1)
            applied += 1
        elif "background: transparent;\n    color: {T['text_on_chrome']};" in src \
                and label.startswith("status"):
            # already has a transparent background; check the specific rule
            head = old.split("\n")[0]
            idx = src.find(head)
            if idx != -1 and "background: transparent;" in src[idx:idx + 140]:
                skipped.append(f"{label} (already applied)")
                continue
            skipped.append(f"{label} (PATTERN NOT FOUND)")
        elif new in src:
            skipped.append(f"{label} (already applied)")
        else:
            skipped.append(f"{label} (PATTERN NOT FOUND)")

    print(f"{applied}/{len(EDITS)} fix(es) applied")
    for s in skipped:
        print(f"  {s}")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(src)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
