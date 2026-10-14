"""Pytest configuration and global fixtures for Vision Studio test suite."""
import os

# Default to offscreen platform for headless and CI test execution so that
# top-level Qt windows are not constrained by host/runner desktop resolutions (e.g. 1024x768).
if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
