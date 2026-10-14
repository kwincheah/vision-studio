"""Verify the design-token substitution emits valid CSS.

A bare-number token without a unit renders as `padding: 2 12;`, which Qt rejects and
silently drops - the widget then keeps its default, so the failure is invisible in a
screenshot.  This extracts every substituted declaration and requires each non-zero
component to carry a unit.
"""
import re
import sys

sys.path.insert(0, ".")
import importlib.util

spec = importlib.util.spec_from_file_location("adt", "scripts/apply_design_tokens.py")
adt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adt)

TABLES = {"font-size": adt.FONT, "font-weight": adt.WEIGHT,
          "border-radius": adt.RADIUS, "padding": adt.PADDING,
          "margin": adt.MARGIN, "min-height": adt.MIN_H}
LENGTH_PROPS = {"font-size", "border-radius", "min-height", "padding", "margin"}

#: a complete token expression followed by its unit, e.g. {T['sp_base']}px
COMPONENT = re.compile(r"\{[A-Za-z_]+\[['\"][a-z_0-9]+['\"]\]\}(px|%|)")

failures = 0
checked = 0
for prop, table in TABLES.items():
    for literal in table:
        src = f"    {prop}: {literal};\n"
        out, n = adt._sub_prop(src, prop, table, "T")
        checked += 1
        if n != 1:
            print(f"FAIL  {prop}: {literal!r} was not substituted -> {out.strip()!r}")
            failures += 1
            continue
        body = out.split(":", 1)[1].strip().rstrip(";").strip()
        if prop not in LENGTH_PROPS:
            continue
        # Every component must be either `0` or a token expression that ends in a unit.
        # Splitting on whitespace is not enough (a token contains a space), so the
        # expressions are matched and each must be followed by `px`/`%`.
        stripped = COMPONENT.sub("X", body)
        leftover = stripped.replace("X", "").strip()
        if leftover not in ("", "0"):
            print(f"FAIL  {prop}: {literal!r} -> bare value {leftover!r} in {body!r}")
            failures += 1
            continue
        for match in COMPONENT.finditer(body):
            if not match.group(1):
                print(f"FAIL  {prop}: {literal!r} -> unitless token in {body!r}")
                failures += 1
                break

print(f"{checked - failures}/{checked} substitutions valid")
sys.exit(1 if failures else 0)

