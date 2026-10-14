"""Find styled labels that sit on the dark chrome and would paint it light.

The status-bar bug generalised: once Qt treats a QLabel as a styled sub-control, the
label paints its own background.  Under the global light `QWidget` rule that fills a
dark strip with the window colour.  This lists every `QLabel`/`QToolButton` rule that
sets a colour but no background, so the ones on chrome can be given an explicit
transparent background.

Run:  python scripts/find_unbackgrounded_labels.py
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.vm_theme import VM_THEME_QSS  # noqa: E402

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
PROP = re.compile(r"([a-z-]+)\s*:\s*([^;]+);")


def main() -> int:
    rows = []
    for m in RULE.finditer(VM_THEME_QSS):
        sel = " ".join(m.group(1).split())
        if sel.startswith("/*") or not sel:
            continue
        # only widget-targeting rules that could be a chrome child
        if not re.match(r"^(QLabel|QToolButton|QPushButton|QWidget)", sel):
            continue
        props = {k: v.strip() for k, v in PROP.findall(m.group(2))}
        if "color" not in props:
            continue
        has_bg = "background" in props or "background-color" in props
        if not has_bg:
            rows.append((sel[:52], props.get("color", "")))

    print(f"{len(rows)} coloured rule(s) without an explicit background:")
    for sel, col in rows:
        print(f"  {sel:54s} color={col}")
    print("\nAny of these placed on a dark strip will paint the strip light; give it "
          "`background: transparent;`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
