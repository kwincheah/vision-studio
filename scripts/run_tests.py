"""Run pytest in-process and dump the full report (workaround for shell truncation)."""
import io
import os
import sys
import contextlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

buf = io.StringIO()
with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
    code = pytest.main(sys.argv[1:] + ["-p", "no:cacheprovider", "--tb=short", "-q"])

report = buf.getvalue()
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "testreport.txt"),
          "w", encoding="utf-8") as fh:
    fh.write(report)
sys.stdout.write(report[-12000:])
sys.exit(code)
