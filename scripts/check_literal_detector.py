"""Sanity-check the literal-token detector against known-bad and known-good code."""
import os
import sys

sys.path.insert(0, ".")
from scripts.find_literal_tokens import scan  # noqa: E402

TMP = os.path.join(os.path.dirname(__file__), "_detector_probe.py")

BAD = '''
from x import THEME
w.setStyleSheet("""
    QLineEdit {
        background: THEME['text_primary'];
        color: THEME["bg_surface_alt"];
    }
""")
'''

GOOD_F = '''
from x import THEME
w.setStyleSheet(f"""
    QLineEdit {{
        background: {THEME['text_primary']};
    }}
""")
'''

GOOD_CODE = '''
from x import THEME
colour = (THEME["status_ok_text"] if ok else THEME["status_error_text"])
html = f"<span style='color:{THEME['text_muted']}'>{ms:.2f}</span>"
'''

cases = [("bad plain block", BAD, 2), ("good f-string", GOOD_F, 0),
         ("good code", GOOD_CODE, 0)]
failures = 0
for label, src, expected in cases:
    open(TMP, "w", encoding="utf-8").write(src)
    hits = scan(TMP)
    ok = len(hits) == expected
    if not ok:
        failures += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label:20s} found {len(hits)}, expected {expected}")
    for h in hits:
        print(f"       line {h[0]}: {h[1]}")

os.remove(TMP)
print(f"\n{len(cases) - failures}/{len(cases)} detector cases correct")
sys.exit(1 if failures else 0)
