"""Normalise the status-bar label rules in the theme stylesheet.

The status strip is dark chrome, so its labels need the chrome ink and a *transparent*
background.  Three separate passes had drifted here: `statusSegment` still carried the
body-dim ink (dark on dark), and the `statusVersion` rule had been lost entirely, so
the build stamp fell back to an inline colour.  This states all four rules once.

Run:  python scripts/fix_status_bar_rules.py --apply
"""
import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "ui", "vm_theme.py")

RULES = {
    "statusSegment": """QLabel#statusSegment {{
    /* The status strip is dark chrome, so the ink is the chrome tone.  An explicit
       transparent background is required: a QLabel with a colour rule otherwise paints
       its own background, and that filled the whole strip with the window colour. */
    background: transparent;
    color: {T['text_on_chrome']};
    padding: {T['sp_hair']} {T['sp_loose']};
    border-left: 1px solid {T['vm_rail_hover']};
    font-size: {T['fs_body']};
}}""",
    "statusLeading": """QLabel#statusLeading {{
    background: transparent;
    color: {T['text_on_chrome']};
    padding: {T['sp_hair']} {T['sp_loose']};
    font-size: {T['fs_body']};
}}""",
    "statusMessage": """QLabel#statusMessage {{
    background: transparent;
    color: {T['text_on_chrome']};
    padding: {T['sp_hair']} {T['sp_loose']};
    font-size: {T['fs_body']};
}}""",
    "statusVersion": """QLabel#statusVersion {{
    background: transparent;
    color: {T['text_on_chrome']};
    font-size: {T['fs_micro']};
    padding-left: {T['sp_snug']};
}}""",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    changed = []

    # In the f-string template a rule body is wrapped in doubled braces: `{{ ... }}`.
    for name, rule in RULES.items():
        pattern = re.compile(r"QLabel#" + name + r"\s*\{\{.*?\n\}\}", re.S)
        if pattern.search(src):
            src = pattern.sub(lambda _m, r=rule: r, src, count=1)
            changed.append(f"{name} (replaced)")
        else:
            anchor = re.search(r"QLabel#statusMessage\s*\{\{.*?\n\}\}", src, re.S)
            if anchor is None:
                anchor = re.search(r"QStatusBar::item\s*\{\{.*?\n\}\}", src, re.S)
            if anchor is None:
                print("no anchor found for insertion - aborting")
                return 1
            src = src[:anchor.end()] + "\n" + rule + src[anchor.end():]
            changed.append(f"{name} (inserted)")

    print(f"{len(changed)} status rule(s) normalised")
    for c in changed:
        print(f"  {c}")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(src)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
