"""The VisionMaster coverage map must only claim modules that exist, and the checked-in document must be current."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("vm_coverage", ROOT / "scripts" / "vm_coverage.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_claimed_module_is_registered():
    _, bad = _load().build()
    assert not bad, bad


def test_the_checked_in_coverage_document_is_current():
    assert (ROOT / "docs" / "VM_COVERAGE.md").read_text(encoding="utf-8").strip() == _load().render().strip()
