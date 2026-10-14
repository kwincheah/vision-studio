"""Unit-check the input coercion helpers added to the tool base class."""
import sys

sys.path.insert(0, ".")
from vm_clone.core.base_tool import VisionToolBase as V

CASES = [
    ("as_float(None)", V.as_float(None, -1), -1),
    ("as_float(inf)", V.as_float(float("inf"), -1), -1),
    ("as_float(-inf)", V.as_float(float("-inf"), -1), -1),
    ("as_float(nan)", V.as_float(float("nan"), -1), -1),
    ("as_float('abc')", V.as_float("abc", -1), -1),
    ("as_float('42')", V.as_float("42", -1), 42.0),
    ("as_float([])", V.as_float([], -1), -1),
    ("as_float(7)", V.as_float(7, -1), 7.0),
    ("as_point(None)", V.as_point(None), None),
    ("as_point((1,))", V.as_point((1,)), None),
    ("as_point([1,2])", V.as_point([1, 2]), (1.0, 2.0)),
    ("as_point({x,y})", V.as_point({"x": 1, "y": 2}), (1.0, 2.0)),
    ("as_point({cx,cy})", V.as_point({"cx": 3, "cy": 4}), (3.0, 4.0)),
    ("as_point('garbage')", V.as_point("garbage"), None),
    ("as_line(dict ok)", V.as_line({"x1": 1, "y1": 2, "x2": 3, "y2": 4}), (1.0, 2.0, 3.0, 4.0)),
    ("as_line(partial)", V.as_line({"x1": 1, "y1": 2}), None),
    ("as_line({})", V.as_line({}), None),
    ("as_line(3-elem)", V.as_line([1, 2, 3]), None),
    ("as_line(4-elem)", V.as_line([1, 2, 3, 4]), (1.0, 2.0, 3.0, 4.0)),
    ("as_line(pairs)", V.as_line([(1, 2), (3, 4)]), (1.0, 2.0, 3.0, 4.0)),
    ("as_line('garbage')", V.as_line("garbage"), None),
    ("as_line(None)", V.as_line(None), None),
]

failures = 0
for label, got, want in CASES:
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label:22s} got={got!r} want={want!r}")

# array-returning helpers
arr = V.as_point_list([[1, 2], [3, 4]])
print("as_point_list ok shape:", None if arr is None else arr.shape)
for label, val, want_none in (
    ("ragged (3,3)", [[1, 2, 3], [4, 5, 6]], True),
    ("empty", [], True),
    ("2 points min 3", [[1, 2], [3, 4]], True),
    ("None", None, True),
    ("string", "garbage", True),
    ("1-D", [1, 2, 3], True),
    ("with nan", [[1, 2], [float("nan"), 4]], True),
):
    m = 3 if "min 3" in label else 1
    out = V.as_point_list(val, m)
    got_none = out is None
    ok = got_none == want_none
    if not ok:
        failures += 1
    print(f"{'ok  ' if ok else 'FAIL'} as_point_list({label:16s}) -> "
          f"{'None' if got_none else out.shape}")

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
