"""A module must not leak numeric warnings, and must not report OK on a broken kernel.

`Surface Defect Filter` guarded one of its two divisions by the ridge width but not the
other, so `std_dev = 0` divided by zero and `std_dev = nan` produced an all-nan kernel -
and the module reported **OK** in both cases.  A warning is not a failure on its own, but
in an inspection tool it means the picture handed to the operator is not the picture the
parameters describe, so it is treated as one here.
"""
import math
import warnings

import numpy as np
import pytest

import apex_vision.tools  # noqa: F401 - registers the tools
from apex_vision.core.registry import create_tool_instance

#: Values that reach a float parameter without passing a coercion layer.
HOSTILE_WIDTHS = [0, -0.0, -1.5, -100, 0.001, float("nan"), float("inf"),
                  float("-inf"), 1e9]


def _image():
    return np.full((64, 64, 3), 128, dtype=np.uint8)


def _run(tool_name: str, **params):
    tool = create_tool_instance(tool_name, "__warn_probe__")
    for key, value in params.items():
        tool.parameters[key] = value
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = tool.execute({"Image": _image()})
    return result, caught


@pytest.mark.parametrize("sigma", HOSTILE_WIDTHS)
def test_surface_defect_filter_does_not_leak_numeric_warnings(sigma):
    result, caught = _run("Surface Defect Filter", std_dev=sigma, roi=[0, 0, 0, 0])
    numeric = [w for w in caught
               if issubclass(w.category, (RuntimeWarning, UserWarning))]
    assert not numeric, (
        f"std_dev={sigma!r} raised {len(numeric)} numeric warning(s), first: "
        f"{numeric[0].message} at {numeric[0].filename}:{numeric[0].lineno}")


@pytest.mark.parametrize("sigma", HOSTILE_WIDTHS)
def test_surface_defect_filter_output_stays_finite(sigma):
    """A nan kernel would produce a nan image that looks like a valid result."""
    result, _caught = _run("Surface Defect Filter", std_dev=sigma, roi=[0, 0, 0, 0])
    out = (result.outputs or {}).get("Image")
    assert out is not None, f"std_dev={sigma!r} produced no image"
    values = np.asarray(out, dtype=np.float64)
    assert np.isfinite(values).all(), (
        f"std_dev={sigma!r} produced non-finite pixels")


@pytest.mark.parametrize("sigma", [0.5, 1.0, 1.5, 3.0, 8.0])
def test_surface_defect_filter_normal_widths_still_work(sigma):
    """The guard must not break the parameter's usable range."""
    result, caught = _run("Surface Defect Filter", std_dev=sigma, roi=[0, 0, 0, 0])
    assert not [w for w in caught if issubclass(w.category, RuntimeWarning)]
    assert (result.outputs or {}).get("Image") is not None


def test_ridge_kernel_is_finite_for_every_hostile_width():
    """The kernel is where the division happens, so it is checked directly."""
    from apex_vision.tools.vm_defect2 import ridge_kernel

    for sigma in HOSTILE_WIDTHS:
        for length, across in ((21, 9), (3, 3), (1, 1), (64, 64)):
            kernel = ridge_kernel(0.0, length, across, sigma)
            assert kernel.size, f"empty kernel for sigma={sigma!r}"
            assert np.isfinite(kernel).all(), (
                f"non-finite kernel for sigma={sigma!r} ({length}x{across})")
            assert np.abs(kernel).sum() > 0, (
                f"all-zero kernel for sigma={sigma!r} ({length}x{across})")


def test_ridge_kernel_is_zero_mean():
    """A flat surface must give no response, whatever the width."""
    from apex_vision.tools.vm_defect2 import ridge_kernel

    for sigma in (0.5, 1.5, 4.0):
        kernel = ridge_kernel(30.0, 21, 9, sigma)
        assert math.isclose(float(kernel.sum()), 0.0, abs_tol=1e-6), (
            f"kernel for sigma={sigma} is not zero-mean (sum={kernel.sum()})")
