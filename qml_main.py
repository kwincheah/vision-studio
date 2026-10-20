"""Run the QML user interface. Identical to ``python main.py`` (kept for convenience)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vm_clone.qml_app import run

if __name__ == "__main__":
    sys.exit(run())
