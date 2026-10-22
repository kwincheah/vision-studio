"""Prove the parameter-type invariant holds by fuzzing every tool's public API.

an earlier audit script reports ~80 unguarded `int()`/`float()` conversions of
parameters.  Those are safe only if a parameter can never *hold* a wrong-typed value,
which is what `VisionToolBase._coerce_param` guarantees.  This test attacks the
invariant from the outside: it drives `set_param` and `load_dict` with hostile values
for every parameter of every tool and then executes the tool, so a hole in the
boundary shows up as a crash rather than staying a latent hazard.

Run:  python -m pytest tests/test_parameter_fuzz.py
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apex_vision.core.base_tool import ToolStatus  # noqa: E402
from apex_vision.core.registry import list_all_tools, create_tool_instance  # noqa: E402
import apex_vision.tools  # noqa: E402,F401

#: Values chosen to break a numeric conversion in every way that matters.
HOSTILE = [
    None, "", "   ", "abc", "1e999", "0x10", "nan", "inf", "-inf",
    float("nan"), float("inf"), float("-inf"), [], {}, set(), object(),
    -1, 0, 10 ** 18, 1.5, True, False, (1, 2), b"bytes",
]


def _image_for(tool):
    """A valid image for whichever port the tool reads."""
    return np.full((48, 64, 3), 128, dtype=np.uint8)


def _sandbox_any_output(tool, tmp_path):
    """Point any path-like parameter at a temporary directory."""
    for key, value in list(tool.parameters.items()):
        if isinstance(value, str) and ("dir" in key or "path" in key or "folder" in key):
            tool.parameters[key] = str(tmp_path)
    return tool


@pytest.fixture()
def hermetic_cwd(tmp_path, monkeypatch):
    """Run the test with the working directory inside `tmp_path`.

    Necessary, not cosmetic: the fuzz deliberately bypasses the parameter coercion
    boundary, so a hostile value reaches a parameter that is used as a *file path*
    (the `Image Output` module writes an image to `save_directory`, which resolves
    relative to the working directory).  Before this, a fuzz run created ~480 PNGs in
    directories named `nan`, `abc`, `inf` ... in the repository root.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("tool_name", sorted(list_all_tools()))
def test_every_parameter_survives_hostile_values(tool_name, tmp_path, hermetic_cwd):
    """Every tool must still execute after any parameter takes any hostile value."""
    tool = _sandbox_any_output(
        create_tool_instance(tool_name, instance_id=f"__fuzz_{tool_name}__"), tmp_path)
    param_names = list(tool.parameters.keys())
    if not param_names:
        pytest.skip("tool declares no parameters")

    ctx = {"Image": _image_for(tool), "width": 64, "height": 48, "trigger": True}

    failures = []
    for name in param_names:
        for bad in HOSTILE:
            tool = _sandbox_any_output(
                create_tool_instance(tool_name, instance_id=f"__fuzz_{tool_name}__"),
                tmp_path)
            try:
                tool.set_param(name, bad)
            except Exception as exc:
                failures.append(f"set_param({name!r}, {bad!r}) raised "
                                f"{type(exc).__name__}: {exc}")
                continue

            # the stored value must still be of the parameter's declared type
            stored = tool.get_param(name)
            original = create_tool_instance(
                tool_name, instance_id="__ref__").get_param(name)
            if original is not None and stored is not None:
                if isinstance(original, bool):
                    ok = isinstance(stored, bool)
                elif isinstance(original, int):
                    ok = isinstance(stored, int) and not isinstance(stored, bool)
                elif isinstance(original, float):
                    ok = isinstance(stored, (int, float))
                elif isinstance(original, str):
                    ok = isinstance(stored, str)
                else:
                    ok = True
                if not ok:
                    failures.append(
                        f"{name}={bad!r} stored {type(stored).__name__} "
                        f"(declared {type(original).__name__})")

            try:
                result = tool.execute(dict(ctx))
            except Exception as exc:
                failures.append(f"execute after {name}={bad!r} raised "
                                f"{type(exc).__name__}: {exc}")
                continue
            if result is None:
                failures.append(f"execute after {name}={bad!r} returned None")

    assert not failures, (
        f"{tool_name}: {len(failures)} failure(s):\n  " + "\n  ".join(failures[:12]))


@pytest.mark.parametrize("tool_name", sorted(list_all_tools()))
def test_every_parameter_survives_a_hostile_project_file(tool_name, tmp_path,
                                                         hermetic_cwd):
    """`load_dict` is the path a project file takes, so it gets the same treatment."""
    reference = _sandbox_any_output(
        create_tool_instance(tool_name, instance_id="__ref__"), tmp_path)
    if not reference.parameters:
        pytest.skip("tool declares no parameters")

    ctx = {"Image": _image_for(reference), "width": 64, "height": 48, "trigger": True}
    failures = []

    for name in reference.parameters:
        for bad in HOSTILE:
            tool = _sandbox_any_output(
                create_tool_instance(tool_name, instance_id=f"__load_{tool_name}__"),
                tmp_path)
            try:
                tool.load_dict({"parameters": {name: bad}})
            except Exception as exc:
                failures.append(f"load_dict({name!r}={bad!r}) raised "
                                f"{type(exc).__name__}: {exc}")
                continue
            try:
                result = tool.execute(dict(ctx))
            except Exception as exc:
                failures.append(f"execute after load_dict({name!r}={bad!r}) raised "
                                f"{type(exc).__name__}: {exc}")
                continue
            if result is None:
                failures.append(f"execute after load_dict({name!r}={bad!r}) -> None")

            # a save/load cycle must not lose the parameter
            assert name in tool.parameters, f"{name} disappeared after load_dict"

    assert not failures, (
        f"{tool_name}: {len(failures)} failure(s):\n  " + "\n  ".join(failures[:12]))


@pytest.mark.parametrize("tool_name", sorted(list_all_tools()))
def test_save_load_round_trip_is_stable(tool_name):
    """A parameter survives to_dict -> load_dict unchanged."""
    tool = create_tool_instance(tool_name, instance_id="__rt__")
    if not tool.parameters:
        pytest.skip("tool declares no parameters")

    snapshot = dict(tool.parameters)
    other = create_tool_instance(tool_name, instance_id="__rt2__")
    other.load_dict(tool.to_dict())

    for key, value in snapshot.items():
        got = other.get_param(key)
        if isinstance(value, np.ndarray):
            assert np.array_equal(value, got), key
        else:
            assert got == value, f"{key}: {value!r} -> {got!r}"
