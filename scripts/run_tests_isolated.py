"""Run each test of a module in its own subprocess so Qt crashes are isolated.

Qt hard-crashes (0xC0000409 stack buffer overrun, etc.) abort the whole pytest
process and swallow the report.  Running one test per process keeps the report
readable and pinpoints the offending test.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODULE = sys.argv[1] if len(sys.argv) > 1 else "tests/test_vm_workspace_ui.py"


def collect() -> list:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", MODULE, "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout
    return [m for m in re.findall(r"(tests[\\/][^\s:]+::\w+)", out)]


def main() -> int:
    names = collect()
    print(f"collected {len(names)} tests from {MODULE}")
    failures = []
    for name in names:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", name, "-q", "--tb=short",
             "-p", "no:cacheprovider"],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        tail = (proc.stdout or "").strip().splitlines()
        summary = tail[-1] if tail else "(no output)"
        status = "PASS" if proc.returncode == 0 else f"FAIL(rc={proc.returncode})"
        print(f"{status:>14}  {name.split('::')[-1]}")
        if proc.returncode != 0:
            failures.append((name, proc.returncode, proc.stdout or ""))
    print(f"\n{len(names) - len(failures)}/{len(names)} passed")
    for name, rc, out in failures:
        print("=" * 78)
        print(f"{name}  (returncode {rc})")
        print(out[-3000:])
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
