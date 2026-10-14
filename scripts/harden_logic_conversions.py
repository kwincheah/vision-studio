"""Harden the remaining ungated numeric conversions in the logic tools.

`float()` accepts `NaN` and `inf`, so a `try/except (ValueError, TypeError)` guard
does not actually protect a comparison: every comparison against `NaN` is False, so
the module reports a confident NG verdict instead of flagging the input.  These
replacements route the values through `VisionToolBase.as_float`, which screens
non-finite values as well as non-numerics.

Run:  python scripts/harden_logic_conversions.py --check
      python scripts/harden_logic_conversions.py --apply
"""
import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(ROOT, "vm_clone", "tools", "logic.py")

EDITS = [
    (
        "ConditionBranch",
        '''        val = context.get("Val_In")
        if val is None:
            val = 80.0
        else:
            try:
                val = float(val)
            except (ValueError, TypeError):
                val = 80.0
''',
        '''        # A non-finite value passes `float()` and then makes every comparison
        # False, so NaN used to yield a confident NG verdict.  `as_float` screens
        # NaN/inf as well as None and non-numerics.
        val = self.as_float(context.get("Val_In"), 80.0)
''',
    ),
    (
        "VariableCalculation",
        '''        raw_a = context.get("Val_A", self.get_param("default_a", 10.0))
        raw_b = context.get("Val_B", self.get_param("default_b", 5.0))
        try:
            a = float(raw_a) if raw_a is not None else float(self.get_param("default_a", 10.0))
        except (ValueError, TypeError):
            a = float(self.get_param("default_a", 10.0))
        try:
            b = float(raw_b) if raw_b is not None else float(self.get_param("default_b", 5.0))
        except (ValueError, TypeError):
            b = float(self.get_param("default_b", 5.0))
''',
        '''        # Non-finite operands are screened out here: `float()` accepts them and the
        # arithmetic then silently produced NaN for every downstream consumer.
        fallback_a = self.as_float(self.get_param("default_a", 10.0), 10.0)
        fallback_b = self.as_float(self.get_param("default_b", 5.0), 5.0)
        a = self.as_float(context.get("Val_A"), fallback_a)
        b = self.as_float(context.get("Val_B"), fallback_b)
''',
    ),
    (
        "IfModule",
        '''        val = context.get("Val_In", 50.0)
        try:
            fval = float(val)
        except (ValueError, TypeError):
            fval = 0.0
''',
        '''        # See ConditionBranch: a NaN operand would compare False against the range
        # and report a confident NG instead of a usable value.
        fval = self.as_float(context.get("Val_In"), 50.0)
''',
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    src = open(TARGET, encoding="utf-8").read()
    applied, skipped = 0, []
    for label, old, new in EDITS:
        if old in src:
            src = src.replace(old, new, 1)
            applied += 1
        elif new in src:
            skipped.append(f"{label} (already applied)")
        else:
            skipped.append(f"{label} (PATTERN NOT FOUND)")
    print(f"{applied}/{len(EDITS)} conversion(s) hardened")
    for s in skipped:
        print(f"  {s}")
    if args.apply:
        open(TARGET, "w", encoding="utf-8").write(src)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
