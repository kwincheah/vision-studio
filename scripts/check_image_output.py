"""Verify the Image Output module's save policy and write verification."""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, ".")
from vm_clone.core.registry import create_tool_instance
import vm_clone.tools  # noqa: F401

tmp = tempfile.mkdtemp(prefix="vm_imgout_")
tool = create_tool_instance("Image Output", "o")
tool.set_param("save_directory", tmp)
img = np.full((40, 50, 3), 128, dtype=np.uint8)

CASES = [
    ("always save", "Always Save", {"Image": img}, True),
    ("trigger False", "Always Save", {"Image": img, "Trigger": False}, False),
    ("trigger True", "Always Save", {"Image": img, "Trigger": True}, True),
    ("Only on NG, result OK", "Only on NG", {"Image": img, "Result": True}, False),
    ("Only on NG, result NG", "Only on NG", {"Image": img, "Result": False}, True),
    ("Only on OK, result OK", "Only on OK", {"Image": img, "Result": True}, True),
    ("Only on OK, result NG", "Only on OK", {"Image": img, "Result": False}, False),
    ("status string OK", "Only on NG", {"Image": img, "Status": "OK"}, False),
    ("status string NG", "Only on NG", {"Image": img, "Status": "NG"}, True),
    ("no image", "Always Save", {}, False),
]

failures = 0
for label, mode, ctx, expect_write in CASES:
    tool.set_param("save_mode", mode)
    before = len(os.listdir(tmp))
    result = tool.execute(ctx)
    wrote = len(os.listdir(tmp)) > before
    ok = wrote == expect_write
    # a save must never report OK without a file, and a skip must say so
    if expect_write and result.status.value != "OK":
        ok = False
    if not ok:
        failures += 1
    print(f"{'ok  ' if ok else 'FAIL'} {label:24s} wrote={wrote!s:5s} "
          f"status={result.status.value:5s} {result.message[:46]}")

# a write into an unwritable path must be reported, never claimed as success
tool.set_param("save_mode", "Always Save")
tool.set_param("save_directory", os.path.join(tmp, "a_file_not_a_dir"))
open(os.path.join(tmp, "a_file_not_a_dir"), "w").close()
res = tool.execute({"Image": img})
ok = res.status.value != "OK"
print(f"{'ok  ' if ok else 'FAIL'} {'unwritable directory':24s} "
      f"status={res.status.value:5s} {res.message[:46]}")
if not ok:
    failures += 1

# an unsupported extension must be reported via imwrite's return value
tool.set_param("save_directory", tmp)
tool.set_param("file_format", "xyz")
res = tool.execute({"Image": img})
ok = res.status.value != "OK"
print(f"{'ok  ' if ok else 'FAIL'} {'unsupported format':24s} "
      f"status={res.status.value:5s} {res.message[:46]}")
if not ok:
    failures += 1

print(f"\n{failures} failure(s)")
sys.exit(1 if failures else 0)
