"""Behavioural tests for the five tools the coverage matrix found untested.

These had no dedicated test: they were only exercised by the generic audits, which
prove a tool does not crash but not that it computes the right thing.  Each test here
asserts a *known* result.

  * `Geometry Generation` - a datum cross must sit at the configured centre.
  * `Image Morphology`    - an open must remove speckle and preserve the large blob.
  * `Color Extraction`    - a green field must be detected and a red one rejected.
  * `TCP Send`            - the payload must honour the prefix/suffix/format options.
  * `Camera IO`           - the strobe and OK/NG lines must follow the verdict and
    the invert switch.
"""
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.core.base_tool import ToolStatus  # noqa: E402
from vm_clone.core.registry import create_tool_instance  # noqa: E402
import vm_clone.tools  # noqa: E402,F401


def make(name: str):
    return create_tool_instance(name, instance_id=f"__t_{name}__")


# ---------------------------------------------------------------------------
# Geometry Generation
# ---------------------------------------------------------------------------
def test_geometry_generation_cross_is_centred():
    tool = make("Geometry Generation")
    tool.set_param("geom_type", "Datum Cross")
    tool.set_param("center_x", 320.0)
    tool.set_param("center_y", 240.0)
    result = tool.execute({})
    assert result.status == ToolStatus.OK, result.message
    assert result.outputs["Point"] == pytest.approx((320.0, 240.0))
    # the crosshair overlay must be drawn at the configured centre
    cross = [o for o in result.overlays if o.get("type") == "cross"]
    assert cross, "a datum cross must emit a cross overlay"
    assert cross[0]["pt"] == pytest.approx((320.0, 240.0))


def test_geometry_generation_circle_uses_the_radius():
    tool = make("Geometry Generation")
    tool.set_param("geom_type", "Reference Circle")
    tool.set_param("center_x", 100.0)
    tool.set_param("center_y", 150.0)
    tool.set_param("radius", 40.0)
    result = tool.execute({})
    assert result.status == ToolStatus.OK, result.message
    circle = result.outputs["Circle"]
    assert (circle["cx"], circle["cy"]) == pytest.approx((100.0, 150.0))
    assert circle["r"] == pytest.approx(40.0)


def test_geometry_generation_line_honours_its_endpoints():
    tool = make("Geometry Generation")
    tool.set_param("geom_type", "Reference Line")
    tool.set_param("line_p1", [10.0, 20.0])
    tool.set_param("line_p2", [110.0, 220.0])
    result = tool.execute({})
    assert result.status == ToolStatus.OK, result.message
    line = result.outputs["Line"]
    assert (line["x1"], line["y1"]) == pytest.approx((10.0, 20.0))
    assert (line["x2"], line["y2"]) == pytest.approx((110.0, 220.0))


@pytest.mark.parametrize("param,bad", [
    ("center_x", None), ("center_x", "nonsense"), ("center_x", float("nan")),
    ("center_x", float("inf")), ("center_y", None), ("center_y", []),
    ("radius", None), ("radius", "x"), ("radius", float("nan")),
    ("line_p1", None), ("line_p1", "x"), ("line_p1", [1]),
    ("line_p2", None), ("line_p2", {}),
])
def test_geometry_generation_survives_bad_parameters(param, bad):
    """Every geometry knob is operator-editable and must never raise.

    These previously escaped as `TypeError`/`ValueError`/`IndexError` and reached the
    operator only as the pipeline's generic "Exception: ..." message.
    """
    tool = make("Geometry Generation")
    tool.set_param(param, bad)
    result = tool.execute({})
    assert result is not None
    assert result.status in (ToolStatus.OK, ToolStatus.NG, ToolStatus.ERROR)
    if result.status == ToolStatus.OK:
        point = result.outputs.get("Point")
        if isinstance(point, (list, tuple)) and len(point) == 2:
            assert all(np.isfinite(float(v)) for v in point)
        circle = result.outputs.get("Circle")
        if isinstance(circle, dict):
            assert np.isfinite(circle["cx"]) and np.isfinite(circle["cy"])
            assert circle["r"] >= 0, "a negative radius reached the output"


def test_geometry_generation_negative_radius_is_made_positive():
    tool = make("Geometry Generation")
    tool.set_param("radius", -25.0)
    result = tool.execute({})
    assert result.status == ToolStatus.OK
    assert result.outputs["Circle"]["r"] == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Image Morphology
# ---------------------------------------------------------------------------
def _speckled_blob() -> np.ndarray:
    """A large white square plus isolated single-pixel speckle."""
    img = np.zeros((80, 100), dtype=np.uint8)
    img[20:60, 25:75] = 255
    rng = np.random.default_rng(7)
    for _ in range(120):
        y, x = rng.integers(0, 80), rng.integers(0, 100)
        img[y, x] = 255
    return img


def test_morphology_open_removes_speckle_and_keeps_the_blob():
    tool = make("Image Morphology")
    tool.set_param("operation", "Open")
    tool.set_param("kernel_size", 3)
    tool.set_param("iterations", 1)
    result = tool.execute({"Image": _speckled_blob()})
    assert result.status == ToolStatus.OK, result.message
    out = result.outputs["Image"]
    assert isinstance(out, np.ndarray)
    assert out.shape[:2] == (80, 100)

    src_area = int((_speckled_blob() > 127).sum())
    out_area = int((out > 127).sum())
    # the speckle must be gone, and the blob must survive
    assert out_area < src_area, "opening did not remove any speckle"
    assert out_area > 40 * 50 * 0.9, (
        f"opening destroyed the large blob: {out_area} px remain")


def test_morphology_close_fills_a_small_hole():
    img = np.zeros((80, 100), dtype=np.uint8)
    img[20:60, 25:75] = 255
    img[38:42, 48:52] = 0            # a 4x4 hole
    tool = make("Image Morphology")
    tool.set_param("operation", "Close")
    tool.set_param("kernel_size", 5)
    result = tool.execute({"Image": img})
    assert result.status == ToolStatus.OK
    out = result.outputs["Image"]
    assert (out[38:42, 48:52] > 127).all(), "closing did not fill the hole"


def test_morphology_dilate_grows_and_erode_shrinks():
    img = np.zeros((60, 60), dtype=np.uint8)
    img[25:35, 25:35] = 255
    base = int((img > 127).sum())

    dil = make("Image Morphology")
    dil.set_param("operation", "Dilate")
    dil.set_param("kernel_size", 3)
    dilated = int((dil.execute({"Image": img}).outputs["Image"] > 127).sum())

    ero = make("Image Morphology")
    ero.set_param("operation", "Erode")
    ero.set_param("kernel_size", 3)
    eroded = int((ero.execute({"Image": img}).outputs["Image"] > 127).sum())

    assert dilated > base, f"dilate did not grow: {base} -> {dilated}"
    assert eroded < base, f"erode did not shrink: {base} -> {eroded}"


@pytest.mark.parametrize("kernel", [0, -1, -2, 2, 4, 999, 100000, None, "x", float("nan")])
def test_morphology_survives_bad_kernel(kernel):
    """OpenCV asserts on a zero/negative kernel and an even size shifts the result.

    The tool must coerce to a usable odd kernel instead of raising out of `int()` or
    tripping cv::normalizeAnchor.
    """
    tool = make("Image Morphology")
    tool.set_param("kernel_size", kernel)
    result = tool.execute({"Image": _speckled_blob()})
    assert result is not None
    assert result.status == ToolStatus.OK, result.message
    assert isinstance(result.outputs["Image"], np.ndarray)


@pytest.mark.parametrize("kernel,expected", [(0, 1), (-3, 1), (2, 3), (4, 5), (7, 7)])
def test_morphology_kernel_is_coerced_to_a_positive_odd_number(kernel, expected):
    tool = make("Image Morphology")
    tool.set_param("kernel_size", kernel)
    result = tool.execute({"Image": _speckled_blob()})
    assert f"k={expected}" in result.message, result.message


@pytest.mark.parametrize("iters", [0, -1, None, "x", 1e12])
def test_morphology_survives_bad_iterations(iters):
    tool = make("Image Morphology")
    tool.set_param("iterations", iters)
    result = tool.execute({"Image": _speckled_blob()})
    assert result is not None


@pytest.mark.parametrize("bad", [None, np.zeros((0, 0, 3), dtype=np.uint8),
                                 np.zeros((1, 1), dtype=np.uint8), "x", 0])
def test_morphology_survives_bad_image(bad):
    tool = make("Image Morphology")
    result = tool.execute({"Image": bad})
    assert result is not None
    assert result.status != ToolStatus.OK or result.outputs


# ---------------------------------------------------------------------------
# Color Extraction
# ---------------------------------------------------------------------------
def _solid_bgr(blue: int, green: int, red: int, w: int = 120, h: int = 90) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = (blue, green, red)
    return img


def test_color_extraction_finds_a_green_field():
    tool = make("Color Extraction")
    tool.set_param("preset_color", "Green")
    green = _solid_bgr(40, 200, 40)
    result = tool.execute({"Image": green})
    assert result.status == ToolStatus.OK, result.message
    ratio = result.outputs.get("Color_Ratio")
    assert ratio is not None
    assert ratio > 50.0, f"a fully green field reported {ratio}% green"
    assert result.outputs.get("Pixel_Count", 0) > 0


def test_color_extraction_rejects_a_red_field():
    tool = make("Color Extraction")
    tool.set_param("preset_color", "Green")
    red = _solid_bgr(40, 40, 200)
    result = tool.execute({"Image": red})
    assert result is not None
    ratio = result.outputs.get("Color_Ratio", 0.0)
    assert ratio < 10.0, f"a red field reported {ratio}% green"


def test_color_extraction_splits_green_and_red_halves():
    tool = make("Color Extraction")
    tool.set_param("preset_color", "Green")
    img = np.zeros((90, 120, 3), dtype=np.uint8)
    img[:, :60] = (40, 200, 40)      # green half
    img[:, 60:] = (40, 40, 200)      # red half
    result = tool.execute({"Image": img})
    assert result.status == ToolStatus.OK
    ratio = result.outputs["Color_Ratio"]
    assert 35.0 < ratio < 65.0, f"a half-green image reported {ratio}%"


def test_color_extraction_mask_matches_the_ratio():
    tool = make("Color Extraction")
    tool.set_param("preset_color", "Green")
    img = np.zeros((90, 120, 3), dtype=np.uint8)
    img[:, :60] = (40, 200, 40)
    result = tool.execute({"Image": img})
    mask = result.outputs.get("Mask")
    if isinstance(mask, np.ndarray):
        mask_ratio = 100.0 * float((mask > 0).sum()) / float(mask.size)
        assert abs(mask_ratio - result.outputs["Color_Ratio"]) < 8.0


@pytest.mark.parametrize("colour", ["Green", "Red", "Blue", "Yellow", "Cyan",
                                    "Magenta", "Unknown", "", None])
def test_color_extraction_accepts_every_preset(colour):
    tool = make("Color Extraction")
    tool.set_param("preset_color", colour)
    result = tool.execute({"Image": _solid_bgr(40, 200, 40)})
    assert result is not None
    if result.status == ToolStatus.OK:
        ratio = result.outputs.get("Color_Ratio")
        assert ratio is None or np.isfinite(float(ratio))


@pytest.mark.parametrize("bad", [None, np.zeros((0, 0, 3), dtype=np.uint8),
                                 "x", np.zeros((30, 30), dtype=np.uint8)])
def test_color_extraction_survives_bad_image(bad):
    tool = make("Color Extraction")
    result = tool.execute({"Image": bad})
    assert result is not None


# ---------------------------------------------------------------------------
# TCP Send
# ---------------------------------------------------------------------------
def test_tcp_send_builds_the_configured_payload():
    tool = make("TCP Send")
    tool.set_param("mode", "Simulation (Loopback Log)")
    tool.set_param("prefix", "VM_RES,")
    tool.set_param("suffix", "\\r\\n")
    result = tool.execute({"Data": "NG"})
    assert result.status == ToolStatus.OK, result.message
    message = result.outputs["Last_Message"]
    # the configured escape text must become real control characters on the wire
    assert message == "VM_RES,NG\r\n", f"payload was {message!r}"
    assert result.outputs["Sent_Bytes"] == len(message.encode("utf-8"))


@pytest.mark.parametrize("suffix,expected_tail", [
    ("\\r\\n", "\r\n"), ("\\n", "\n"), ("\\r", "\r"), ("\\t", "\t"),
    ("", ""), ("END", "END"), ("|\\r\\n", "|\r\n"),
])
def test_tcp_send_decodes_configured_escape_sequences(suffix, expected_tail):
    tool = make("TCP Send")
    tool.set_param("prefix", "")
    tool.set_param("suffix", suffix)
    result = tool.execute({"Data": "X"})
    assert result.outputs["Last_Message"] == "X" + expected_tail


def test_tcp_send_without_prefix_or_suffix():
    tool = make("TCP Send")
    tool.set_param("prefix", "")
    tool.set_param("suffix", "")
    result = tool.execute({"Data": "42"})
    assert result.status == ToolStatus.OK
    assert result.outputs["Last_Message"] == "42"


@pytest.mark.parametrize("payload,expected", [
    ("NG", "NG"), (1, "1"), (2.5, "2.5"), (2.0, "2"), (True, "1"), (False, "0"),
    (None, ""), (0, "0"),
])
def test_tcp_send_serialises_every_payload_type(payload, expected):
    """`None` used to transmit the literal word "None" to the PLC."""
    tool = make("TCP Send")
    tool.set_param("prefix", "")
    tool.set_param("suffix", "")
    result = tool.execute({"Data": payload})
    assert result is not None
    assert result.status == ToolStatus.OK
    assert result.outputs["Last_Message"] == expected


def test_tcp_send_json_format_for_a_mapping():
    tool = make("TCP Send")
    tool.set_param("format", "JSON")
    tool.set_param("suffix", "")
    result = tool.execute({"Data": {"verdict": "NG", "count": 7}})
    assert result.status == ToolStatus.OK
    assert result.outputs["Last_Message"] == '{"verdict": "NG", "count": 7}'


def test_tcp_send_inactive_trigger_does_not_transmit():
    """The `Trigger` port must actually gate the transmission."""
    tool = make("TCP Send")
    result = tool.execute({"Data": "NG", "Trigger": False})
    assert result is not None
    assert result.outputs["Sent_Bytes"] == 0
    assert result.outputs["Last_Message"] == ""
    assert "trigger" in result.message.lower()


def test_tcp_send_active_trigger_transmits():
    tool = make("TCP Send")
    result = tool.execute({"Data": "NG", "Trigger": True})
    assert result.status == ToolStatus.OK
    assert result.outputs["Sent_Bytes"] > 0


def test_tcp_send_reports_an_unreachable_endpoint():
    """A failed send must be reported: an operator needs to know the PLC missed it.

    The previous version swallowed every socket error and still returned OK.
    """
    tool = make("TCP Send")
    tool.set_param("mode", "TCP Client")
    tool.set_param("server_ip", "127.0.0.1")
    tool.set_param("server_port", 1)        # nothing listens here
    result = tool.execute({"Data": "NG"})
    assert result is not None
    assert result.status == ToolStatus.ERROR, (
        f"connecting to a closed port reported {result.status.value}")
    assert result.outputs["Sent_Bytes"] == 0
    assert "127.0.0.1" in result.message


def test_tcp_send_delivers_to_a_listening_socket():
    """A successful send to a real listener must report OK and the exact bytes."""
    import socket
    import threading

    received = []

    def serve():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port_holder.append(srv.getsockname()[1])
        ready.set()
        try:
            conn, _ = srv.accept()
            with conn:
                received.append(conn.recv(256))
        finally:
            srv.close()

    port_holder: list = []
    ready = threading.Event()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert ready.wait(5.0), "test listener did not start"

    tool = make("TCP Send")
    tool.set_param("mode", "TCP Client")
    tool.set_param("server_ip", "127.0.0.1")
    tool.set_param("server_port", port_holder[0])
    tool.set_param("prefix", "VM_RES,")
    tool.set_param("suffix", "\\r\\n")
    result = tool.execute({"Data": "NG"})
    thread.join(timeout=5.0)

    assert result.status == ToolStatus.OK, result.message
    assert received, "the listener received nothing"
    assert received[0] == b"VM_RES,NG\r\n", received[0]


# ---------------------------------------------------------------------------
# Camera IO
# ---------------------------------------------------------------------------
def test_camera_io_ok_verdict_raises_the_ok_line_only():
    tool = make("Camera IO")
    tool.set_param("invert_logic", False)
    result = tool.execute({"Status_In": "OK"})
    assert result.status == ToolStatus.OK, result.message
    assert result.outputs["Line1_OK"] is True
    assert result.outputs["Line2_NG"] is False


def test_camera_io_ng_verdict_raises_the_ng_line_only():
    tool = make("Camera IO")
    tool.set_param("invert_logic", False)
    result = tool.execute({"Status_In": "NG"})
    assert result.status == ToolStatus.OK
    assert result.outputs["Line1_OK"] is False
    assert result.outputs["Line2_NG"] is True


def test_camera_io_strobe_fires_and_can_be_inverted():
    tool = make("Camera IO")
    tool.set_param("strobe_active_high", True)
    high = tool.execute({"Status_In": "OK"}).outputs["Line0_Strobe"]

    tool2 = make("Camera IO")
    tool2.set_param("strobe_active_high", False)
    low = tool2.execute({"Status_In": "OK"}).outputs["Line0_Strobe"]

    assert high is True
    assert low is False


def test_camera_io_invert_logic_swaps_the_verdict_lines():
    tool = make("Camera IO")
    tool.set_param("invert_logic", True)
    result = tool.execute({"Status_In": "OK"})
    assert result.status == ToolStatus.OK
    # inverted: an OK verdict drives the NG line
    assert result.outputs["Line1_OK"] is False
    assert result.outputs["Line2_NG"] is True


@pytest.mark.parametrize("status", ["OK", "NG", "", "garbage", None, 0, 1, True, False])
def test_camera_io_accepts_any_status_value(status):
    tool = make("Camera IO")
    result = tool.execute({"Status_In": status})
    assert result is not None
    if result.status == ToolStatus.OK:
        for key in ("Line0_Strobe", "Line1_OK", "Line2_NG"):
            assert isinstance(result.outputs[key], bool)


def test_camera_io_pulse_duration_is_configurable():
    tool = make("Camera IO")
    tool.set_param("pulse_duration_ms", 50)
    result = tool.execute({"Status_In": "OK"})
    assert result is not None
    assert result.status == ToolStatus.OK
    assert tool.get_param("pulse_duration_ms") == 50
