"""Capture a true "before" frame from the pre-refinement commit.

The stylesheets in `vm_theme.py` embed literal colour values (the f-strings are
resolved at import), so simply overriding the palette cannot reproduce the old
look.  A clean `git worktree` at the pre-refinement commit renders the genuinely
old interface, and today's layout code renders the new one — so the pair differs
only by the refinement, at identical window sizes.

Run:  python scripts/capture_before_worktree.py [commit]
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORK = os.path.join(ROOT, ".before_wt")
AUDIT = os.path.join(ROOT, "docs", "screenshots", "audit")
COMMIT = sys.argv[1] if len(sys.argv) > 1 else "HEAD"

SIZES = [(925, 765), (1400, 760), (1120, 760)]

RUNNER = """
import sys
sys.path.insert(0, r"{root}")
from PyQt6.QtWidgets import QApplication
from vm_clone.ui.styles import initialize_app_fonts
app = QApplication([])
initialize_app_fonts(app)
from vm_clone.ui.main_window import VisionMasterMainWindow
win = VisionMasterMainWindow()
win.resize({w}, {h})
win.show()
for _ in range(26):
    app.processEvents()
win.grab().save(r"{out}")
print("saved", r"{out}")
"""


def main() -> int:
    if os.path.exists(WORK):
        subprocess.run(["git", "worktree", "remove", "--force", WORK],
                       cwd=ROOT, capture_output=True)
    subprocess.run(["git", "worktree", "add", "--detach", WORK, COMMIT],
                   cwd=ROOT, check=True, capture_output=True)
    print(f"worktree at {COMMIT} -> {WORK}")

    os.makedirs(AUDIT, exist_ok=True)
    try:
        for w, h in SIZES:
            out = os.path.join(AUDIT, f"60_before_{w}x{h}.png")
            code = RUNNER.format(root=WORK, w=w, h=h, out=out)
            subprocess.run([sys.executable, "-c", code], cwd=WORK, check=True,
                           capture_output=True)
            print(f"  captured {w}x{h}")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", WORK],
                       cwd=ROOT, capture_output=True)
    print("worktree removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
