"""Regression tests for the second-pass bug-pattern sweep.

`scripts/audit_bug_patterns.py` scans for the *code shapes* that produced the defects
the first audit found, rather than for specific values.  These tests pin the two
actionable results of that sweep:

  * a parameter must not be able to hold a value of the wrong type, because a project
    file written by an older build (or edited by hand) can otherwise put `None` or a
    string into a numeric knob, and ~80 call sites convert parameters with a bare
    `int()`/`float()` at the point of use;
  * the barcode decoder's absent module and its variable return arity must not be
    reported as "no barcode found".
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.core.base_tool import ToolStatus  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


def make(name: str):
    return create_tool_instance(name, instance_id=f"__p_{name}__")


# ---------------------------------------------------------------------------
# Parameter type integrity
# ---------------------------------------------------------------------------
def test_set_param_coerces_to_the_declared_type():
    """A parameter's type is fixed by the default its `_init_parameters` supplies."""
    tool = make("Image Morphology")
    assert isinstance(tool.get_param("kernel_size"), int)

    tool.set_param("kernel_size", "5")
    assert tool.get_param("kernel_size") == 5
    tool.set_param("kernel_size", 7.0)
    assert tool.get_param("kernel_size") == 7
    tool.set_param("kernel_size", True)
    assert tool.get_param("kernel_size") == 1


@pytest.mark.parametrize("bad", ["nonsense", None, [], {}, object()])
def test_uncoercible_values_fall_back_to_the_current_value(bad):
    """A value that cannot be a number must not be stored as one.

    The stored value has to stay usable: every tool converts parameters with a bare
    `int()`/`float()` at the point of use, so a stray `None` crashed the inspection.
    """
    tool = make("Image Morphology")
    tool.set_param("kernel_size", 5)
    tool.set_param("kernel_size", bad)
    assert tool.get_param("kernel_size") == 5


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_parameter_values_are_rejected(bad):
    tool = make("Template Match")
    original = tool.get_param("min_score")
    tool.set_param("min_score", bad)
    assert tool.get_param("min_score") == original
    assert np.isfinite(tool.get_param("min_score"))


def test_float_param_accepts_numeric_strings_and_ints():
    tool = make("Template Match")
    tool.set_param("min_score", "0.9")
    assert tool.get_param("min_score") == pytest.approx(0.9)
    tool.set_param("min_score", 1)
    assert tool.get_param("min_score") == pytest.approx(1.0)
    assert isinstance(tool.get_param("min_score"), float)


def test_bool_param_coerces_from_strings_and_ints():
    tool = make("Camera IO")
    for text, expected in (("yes", True), ("true", True), ("1", True), ("on", True),
                           ("no", False), ("false", False), ("0", False), ("off", False)):
        tool.set_param("invert_logic", text)
        assert tool.get_param("invert_logic") is expected, text
    for number, expected in ((1, True), (0, False)):
        tool.set_param("invert_logic", number)
        assert tool.get_param("invert_logic") is expected


def test_string_param_coerces_from_numbers():
    tool = make("TCP Send")
    tool.set_param("prefix", 5)
    assert tool.get_param("prefix") == "5"


def test_structured_parameters_keep_their_shape():
    """Lists, dicts and tuples carry geometry, so their shape is preserved.

    A tuple of the right length written to a list parameter is normalised to that
    parameter's own container type rather than left as a tuple, so a later save/load
    cycle is stable.
    """
    tool = make("L2L Measure")
    tool.set_param("default_l1", [1, 2, 3, 4])
    assert tool.get_param("default_l1") == [1, 2, 3, 4]
    tool.set_param("default_l2", (5, 6, 7, 8))
    assert list(tool.get_param("default_l2")) == [5, 6, 7, 8]


@pytest.mark.parametrize("bad", ["abc", 5, 1.5, None, {}, object()])
def test_structured_parameters_reject_a_wrong_shape(bad):
    """A scalar or string in a geometry parameter broke the unpacking at point of use.

    `x, y, w, h = roi` raised "not enough values to unpack" when a project file put a
    string in an ROI, so the wrong shape is refused in favour of the stored value.
    """
    tool = make("L2L Measure")
    tool.set_param("default_l1", [1, 2, 3, 4])
    tool.set_param("default_l1", bad)
    assert tool.get_param("default_l1") == [1, 2, 3, 4]


def test_structured_parameter_rejects_a_wrong_length():
    tool = make("L2L Measure")
    tool.set_param("default_l1", [1, 2, 3, 4])
    tool.set_param("default_l1", [1, 2])
    assert tool.get_param("default_l1") == [1, 2, 3, 4]


@pytest.mark.parametrize("bad", ["abc", 5, [1, 2], None, {}, 1.5])
def test_roi_parameter_rejects_a_wrong_shape(bad):
    """The ROI is unpacked as four numbers throughout the tools.

    `Defect Detection` stores its ROI as a parameter, so it is the representative case
    (several other tools take the ROI through `get_roi()` with its own defaulting).
    """
    tool = make("Defect Detection")
    original = list(tool.get_param("roi"))
    assert len(original) == 4
    tool.set_param("roi", bad)
    assert list(tool.get_param("roi")) == original


def test_roi_parameter_accepts_a_correct_quadruple():
    tool = make("Defect Detection")
    tool.set_param("roi", [10, 20, 30, 40])
    assert list(tool.get_param("roi")) == [10, 20, 30, 40]


def test_get_roi_tolerates_a_hostile_stored_value():
    """`get_roi` is the accessor most tools use, and must always yield four numbers."""
    tool = make("Image Binarization")
    tool.parameters["roi"] = "not-an-roi"      # bypass the boundary deliberately
    x, y, w, h = tool.get_roi(img_shape=(100, 200))
    assert all(isinstance(v, int) for v in (x, y, w, h))
    assert w >= 1 and h >= 1


# ---------------------------------------------------------------------------
# Project round trip cannot inject a wrong type
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_value", [None, "nonsense", [], {}, float("nan")])
def test_load_dict_cannot_store_a_wrong_typed_parameter(bad_value):
    """A hand-edited or older project file must not break the tool at run time."""
    tool = make("Image Morphology")
    tool.load_dict({"parameters": {"kernel_size": bad_value,
                                   "iterations": bad_value}})
    assert isinstance(tool.get_param("kernel_size"), int)
    assert isinstance(tool.get_param("iterations"), int)

    # and the tool must still run
    result = tool.execute({"Image": np.full((40, 40), 128, dtype=np.uint8)})
    assert result.status == ToolStatus.OK


def test_load_dict_preserves_unknown_keys():
    """Dropping an unrecognised key would silently lose data on a save."""
    tool = make("Image Morphology")
    tool.load_dict({"parameters": {"plugin_specific": 42}})
    assert tool.get_param("plugin_specific") == 42


def test_project_round_trip_preserves_parameter_values():
    from vm_clone.core.pipeline import SolutionManager
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution
    import tempfile

    pipe = create_pcb_inspection_solution()
    solution = SolutionManager(name="coerce_roundtrip")
    solution.flows = {pipe.name: pipe}
    solution.active_flow_name = pipe.name
    solution.set_trigger_flow(pipe.name)

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "rt.vmp")
        solution.save_to_file(path)
        loaded = SolutionManager.load_from_file(path)
        first_flow = next(iter(loaded.flows.values()))
        for nid, node in pipe.nodes.items():
            assert nid in first_flow.nodes
            assert first_flow.nodes[nid].parameters == node.parameters, (
                f"parameters changed for {node.name}")


# ---------------------------------------------------------------------------
# Barcode decoder robustness
# ---------------------------------------------------------------------------
def test_bcr_reports_an_absent_decoder_as_an_error(monkeypatch):
    """A missing OpenCV module is not "no barcode found"."""
    import cv2
    from vm_clone.tools import recognition

    tool = make("BCR Recognition")

    def boom():
        raise AttributeError("module 'cv2' has no attribute 'barcode_BarcodeDetector'")

    monkeypatch.setattr(cv2, "barcode_BarcodeDetector", boom, raising=False)
    result = tool.execute({"Image": np.full((60, 200), 200, dtype=np.uint8)})
    assert result.status == ToolStatus.ERROR
    assert "unavailable" in result.message.lower()


def test_bcr_survives_a_variable_arity_decoder(monkeypatch):
    """`detectAndDecode` returns 3 values in some builds and 4 in others."""
    import cv2

    tool = make("BCR Recognition")

    class ThreeValueDetector:
        def detectAndDecode(self, gray):
            return True, ("ABC123",), ("CODE128",)

    monkeypatch.setattr(cv2, "barcode_BarcodeDetector", ThreeValueDetector,
                        raising=False)
    result = tool.execute({"Image": np.full((60, 200), 200, dtype=np.uint8)})
    assert result.status == ToolStatus.OK, result.message
    assert result.outputs["Barcode_Text"] == "ABC123"
    assert result.outputs["Format"] == "CODE128"


def test_bcr_reports_no_detection_as_ng(monkeypatch):
    import cv2

    tool = make("BCR Recognition")

    class EmptyDetector:
        def detectAndDecode(self, gray):
            return False, (), ()

    monkeypatch.setattr(cv2, "barcode_BarcodeDetector", EmptyDetector, raising=False)
    result = tool.execute({"Image": np.full((60, 200), 200, dtype=np.uint8)})
    assert result.status == ToolStatus.NG
    assert "no 1d barcode" in result.message.lower()


def test_bcr_reports_a_decoder_exception(monkeypatch):
    import cv2

    tool = make("BCR Recognition")

    class BrokenDetector:
        def detectAndDecode(self, gray):
            raise ValueError("not enough values to unpack (expected 4, got 3)")

    monkeypatch.setattr(cv2, "barcode_BarcodeDetector", BrokenDetector, raising=False)
    result = tool.execute({"Image": np.full((60, 200), 200, dtype=np.uint8)})
    assert result.status == ToolStatus.ERROR
    assert "decode failed" in result.message.lower()


def test_bcr_handles_a_tiny_image():
    """The fuzz suite uses very small images; the detector must not raise on them."""
    tool = make("BCR Recognition")
    for shape in ((1, 1), (5, 10), (10, 5)):
        result = tool.execute({"Image": np.zeros(shape, dtype=np.uint8)})
        assert result is not None
        assert result.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR)
