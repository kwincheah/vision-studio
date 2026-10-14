"""Find QSS rules that pair dark ink with a dark chrome surface.

The light-palette conversion turned `text_*` tokens dark, but several rules still
apply them to a *dark* background (the steel chrome, the rail, the image viewport),
which renders near-invisible text.  This walks the generated stylesheet rule by rule,
resolves each `background-color` and `color`, and reports any pair whose contrast is
below the WCAG target for its font size.

Run:  python scripts/audit_qss_contrast.py
"""
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from vm_clone.ui.vm_theme import VM_THEME_QSS  # noqa: E402


def _srgb(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexcol: str) -> float:
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
PROP = re.compile(r"([a-z-]+)\s*:\s*([^;]+);")


def font_px(body: str) -> int:
    m = PROP.search(body) and re.search(r"font-size:\s*(\d+)px", body)
    return int(m.group(1)) if m else 12


def main() -> int:
    css = VM_THEME_QSS
    rows: List[Dict] = []
    for m in RULE.finditer(css):
        sel = " ".join(m.group(1).split())
        if sel.startswith("/*") or not sel:
            continue
        body = m.group(2)
        props = {k: v.strip() for k, v in PROP.findall(body)}
        bg = props.get("background-color")
        fg = props.get("color")
        if not bg or not fg:
            continue
        if not (bg.startswith("#") and fg.startswith("#")):
            continue
        size = font_px(body)
        need = 3.0 if size >= 18 else 4.5
        r = contrast(fg, bg)
        rows.append({"selector": sel[:58], "fg": fg, "bg": bg,
                     "size": size, "ratio": r, "need": need, "ok": r >= need})

    bad = [r for r in rows if not r["ok"]]
    print(f"{len(rows)} rules carry both a colour and a background")
    if bad:
        print(f"\n{len(bad)} below target:")
        for r in bad:
            print(f"  {r['selector']:58s} {r['fg']} on {r['bg']} "
                  f"= {r['ratio']:5.2f} (need {r['need']}) [{r['size']}px]")
    else:
        print("every rule passes its target")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
