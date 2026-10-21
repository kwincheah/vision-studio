import numpy as np

from apex_vision.core.overlays import DEFAULT_LAYERS, render_overlays

OVERLAYS = [
    {"type": "rect", "box": [10, 10, 40, 30], "color": (0, 0, 255), "label": "box"},
    {"type": "circle", "center": (80, 60), "radius": 15, "color": (0, 255, 0), "label": "c"},
    {"type": "line", "pt1": (0, 0), "pt2": (99, 99), "color": (255, 0, 0), "thickness": 2},
    {"type": "cross", "pt": (50, 50), "size": 6, "color": (255, 0, 255)},
    {"type": "text", "text": "hello", "pt": (5, 90), "color": (0, 255, 255)},
]


def blank():
    return np.zeros((100, 120, 3), np.uint8)


def changed(a, b) -> bool:
    return bool((a != b).any())


def test_every_overlay_kind_is_drawn_and_the_input_is_untouched():
    img = blank()
    out = render_overlays(img, OVERLAYS)
    assert not img.any() and out.any() and out.shape == img.shape


def test_layer_switches_hide_their_group_only():
    base = render_overlays(blank(), OVERLAYS)
    no_rois = render_overlays(blank(), OVERLAYS, {"rois": False})
    no_metrics = render_overlays(blank(), OVERLAYS, {"metrics": False})
    no_datums = render_overlays(blank(), OVERLAYS, {"datums": False})
    off = render_overlays(blank(), OVERLAYS, {"overlays": False})
    assert changed(base, no_rois) and changed(base, no_metrics) and changed(base, no_datums)
    assert not off.any()
    assert render_overlays(blank(), OVERLAYS, {"rois": False})[25, 10].sum() == 0   # box edge gone
    assert render_overlays(blank(), OVERLAYS, {"rois": False})[50, 50].any()        # datum still drawn


def test_crosshair_and_histogram_are_extras():
    assert not DEFAULT_LAYERS["crosshair"] and not DEFAULT_LAYERS["histogram"]
    assert render_overlays(blank(), [], {"crosshair": True}).any()
    assert render_overlays(blank(), [], {"histogram": True}).any()


def test_grayscale_none_and_malformed_overlays_are_safe():
    assert render_overlays(None, OVERLAYS) is None
    gray = render_overlays(np.zeros((40, 40), np.uint8), OVERLAYS[:1])
    assert gray.ndim == 3
    junk = [{"type": "rect", "box": "bad"}, {"type": "circle", "center": None}, {"type": "mystery"}, {}]
    assert render_overlays(blank(), junk) is not None
