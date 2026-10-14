"""Tests for the design-system tokens and component conventions.

The audit found 383 hardcoded visual constants, 29 distinct paddings and two competing
typographic channels.  These tests keep the token layer authoritative: every token must
exist and be on its own scale, both font channels must agree, every declared length must
be on-scale, and the load-bearing state rules must stay in place.

See `docs/DESIGN_SYSTEM.md`.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.ui.styles import (  # noqa: E402
    BORDER, FONT_STACK, RADIUS, SIZE, SPACE, THEME, TYPE, WEIGHT,
    control_h, corner_radius, font_px, font_weight, nearest_space, ramp_report,
    space,
)
from vm_clone.ui.styles import INDUSTRIAL_THEME_QSS  # noqa: E402
from vm_clone.ui.vm_theme import VM_THEME_QSS  # noqa: E402

UI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                      "vm_clone", "ui"))
SHEETS = {"industrial": INDUSTRIAL_THEME_QSS, "vm_theme": VM_THEME_QSS}


# ---------------------------------------------------------------------------
# Ramp integrity
# ---------------------------------------------------------------------------
def test_type_ramp_is_ascending_and_distinct():
    sizes = [TYPE[k] for k in ("micro", "caption", "body", "label", "subtitle", "title")]
    assert sizes == sorted(sizes)
    assert len(set(sizes)) == len(sizes), "a duplicate size has no distinct role"


def test_every_ramp_maps_to_a_valid_positive_value():
    for table in (TYPE, WEIGHT, SIZE, SPACE, RADIUS, BORDER):
        for name, value in table.items():
            assert isinstance(value, int), f"{name} is not an int"
            assert value >= 0, f"{name} is negative"


def test_spacing_scale_is_monotonic():
    steps = [SPACE[k] for k in ("none", "hair", "tight", "snug", "base", "loose",
                                "section")]
    assert steps == sorted(steps)
    assert SPACE["none"] == 0


def test_control_sizes_are_usable_tiers():
    """Every height tier must be tall enough to draw a line of body text."""
    minimum = TYPE["body"] + SPACE["tight"]
    for name in ("input", "button", "compact", "toolbar", "tab", "row", "header"):
        assert SIZE[name] >= minimum, f"{name} is too short for body text"


def test_flat_tokens_exist_for_every_role():
    for key in TYPE:
        assert f"fs_{key}" in THEME, f"fs_{key} missing from THEME"
    for key in SIZE:
        assert f"h_{key}" in THEME, f"h_{key} missing from THEME"
    for key in SPACE:
        assert f"sp_{key}" in THEME, f"sp_{key} missing from THEME"
    for key in RADIUS:
        assert f"r_{key}" in THEME, f"r_{key} missing from THEME"
    for key in BORDER:
        assert f"bw_{key}" in THEME, f"bw_{key} missing from THEME"
    for key in WEIGHT:
        assert f"fw_{key}" in THEME, f"fw_{key} missing from THEME"
    assert THEME["font_stack"] == FONT_STACK


def test_accessors_match_their_tables():
    assert font_px("body") == TYPE["body"]
    assert font_px("nonexistent") == TYPE["body"], "unknown role falls back to body"
    assert font_weight("bold") == WEIGHT["bold"]
    assert control_h("input") == SIZE["input"]
    assert space("base") == SPACE["base"]
    assert corner_radius("control") == RADIUS["control"]


@pytest.mark.parametrize("value,expected", [
    (0, 0), (1, 2), (2, 2), (3, 4), (4, 4), (5, 6), (6, 6), (7, 8),
    (8, 8), (9, 8), (10, 12), (11, 12), (12, 12), (14, 16), (15, 16), (99, 16),
])
def test_nearest_space_snaps_onto_the_scale(value, expected):
    """Ties round up, so a control is never tighter than the scale intends."""
    assert nearest_space(value) == expected
    assert nearest_space(value) in SPACE.values()


def test_ramp_report_is_complete():
    report = ramp_report()
    for key in ("type", "weights", "sizes", "spacing", "radius", "border",
                "font_stack"):
        assert key in report
    assert report["font_stack"] == FONT_STACK


# ---------------------------------------------------------------------------
# Both font channels agree
# ---------------------------------------------------------------------------
def test_application_font_matches_the_body_token(qapp):
    """The application font and the stylesheet's body size must not disagree.

    They were set independently before (10 pt versus a 12-13 px stylesheet), which made
    a styled panel and an unstyled widget render text at different sizes.
    """
    from PyQt6.QtGui import QFontMetrics

    font = qapp.font()
    # `initialize_app_fonts` uses a point size, so `pointSize()` must be positive;
    # a pixel-sized font reports -1 and makes internal widgets warn and fall back.
    assert font.pointSize() > 0, "the application font has no usable point size"
    from vm_clone.ui.styles import _point_size_for

    assert font.pointSizeF() == pytest.approx(_point_size_for(TYPE["body"]), abs=0.2)
    # the resolved height must be close to the pixel scale the stylesheet declares
    height = QFontMetrics(font).height()
    assert abs(height - TYPE["body"]) <= 4, (
        f"application font renders {height}px against a {TYPE['body']}px token")


def test_apply_type_sets_the_ramp_size(qapp):
    from PyQt6.QtWidgets import QLabel

    from vm_clone.ui.styles import apply_type

    label = QLabel("x")
    for role in ("micro", "caption", "body", "label", "subtitle", "title"):
        apply_type(label, role)
        assert label.font().pointSize() > 0, f"{role} produced no usable point size"
    apply_type(label, "subtitle", "demibold")
    assert label.font().weight() == label.font().Weight.DemiBold


# ---------------------------------------------------------------------------
# Declared lengths are on-scale
# ---------------------------------------------------------------------------
LENGTH_DECL = re.compile(
    r"(?<!-)\b(font-size|border-radius|padding|margin|min-height|max-height|"
    r"min-width|max-width)\s*:\s*([^;{}]+);")
NUM = re.compile(r"(\d+(?:\.\d+)?)px")
#: structural widths/heights that are layout-driven, not ramp values
STRUCTURAL = {0, 1, 2, 3, 6, 7, 13, 18, 20, 22, 26, 30, 42, 48, 51, 52, 56, 62, 68,
              80, 96, 100, 104, 112, 120, 150, 168, 176, 200, 240, 300, 320, 340,
              380, 400, 446, 520, 818}


@pytest.mark.parametrize("sheet_name", sorted(SHEETS))
def test_stylesheet_lengths_are_on_scale(sheet_name):
    allowed = set(TYPE.values()) | set(SIZE.values()) | set(SPACE.values()) | \
        set(RADIUS.values()) | set(BORDER.values())
    off = []
    for m in LENGTH_DECL.finditer(SHEETS[sheet_name]):
        prop, raw = m.group(1), m.group(2).strip()
        if "{" in raw:
            continue
        for value in NUM.findall(raw):
            px = float(value)
            if px in allowed or px in STRUCTURAL:
                continue
            off.append(f"{prop}: {raw}")
    assert not off, f"{sheet_name} has {len(off)} off-scale value(s): {sorted(set(off))[:8]}"


def test_no_declaration_is_missing_its_unit():
    """`padding: 2 12;` is invalid CSS and Qt silently drops the whole declaration."""
    bad = []
    for name, css in SHEETS.items():
        for m in LENGTH_DECL.finditer(css):
            prop, raw = m.group(1), m.group(2).strip()
            for component in raw.split():
                if component in ("0", "{") or component.startswith("{"):
                    continue
                if prop == "font-weight":
                    continue
                if not re.search(r"px$|%$", component):
                    bad.append(f"{name}: {prop}: {raw}")
    assert not bad, f"unitless declaration(s): {sorted(set(bad))[:8]}"


@pytest.mark.parametrize("sheet_name", sorted(SHEETS))
def test_declared_font_sizes_are_on_the_ramp(sheet_name):
    off = []
    for m in LENGTH_DECL.finditer(SHEETS[sheet_name]):
        if m.group(1) != "font-size":
            continue
        raw = m.group(2).strip()
        if "{" in raw:
            continue
        for value in NUM.findall(raw):
            if int(value) not in TYPE.values():
                off.append(raw)
    assert not off, f"{sheet_name} uses off-ramp font sizes: {sorted(set(off))}"


def test_inline_widget_lengths_are_on_scale():
    """Inline stylesheets in the UI modules must use the scale too."""
    allowed = set(TYPE.values()) | set(SPACE.values()) | set(RADIUS.values())
    off = []
    for fname in sorted(os.listdir(UI_DIR)):
        if not fname.endswith(".py") or fname in ("styles.py", "vm_theme.py"):
            continue
        text = open(os.path.join(UI_DIR, fname), encoding="utf-8").read()
        for m in LENGTH_DECL.finditer(text):
            prop, raw = m.group(1), m.group(2).strip()
            if "{" in raw or prop in ("min-height", "min-width", "max-width",
                                      "max-height"):
                continue
            for value in NUM.findall(raw):
                if int(value) not in allowed:
                    off.append(f"{fname}: {prop}: {raw}")
    assert not off, f"{len(off)} off-scale inline value(s): {sorted(set(off))[:8]}"


# ---------------------------------------------------------------------------
# Load-bearing conventions
# ---------------------------------------------------------------------------
def test_status_labels_declare_a_transparent_background():
    """Otherwise Qt paints the strip with the label's background and hides the chrome."""
    for name in ("statusSegment", "statusLeading", "statusMessage", "statusVersion"):
        m = re.search(r"QLabel#" + name + r"\s*\{([^}]*)\}", VM_THEME_QSS, re.S)
        assert m, f"{name} rule missing"
        assert "background" in m.group(1), f"{name} has no background declaration"
        assert "transparent" in m.group(1), f"{name} background is not transparent"


def test_status_ink_is_the_chrome_tone():
    m = re.search(r"QStatusBar\s*\{([^}]*)\}", VM_THEME_QSS, re.S)
    assert m
    assert THEME["text_on_chrome"] in m.group(1)


def test_global_widget_rule_is_not_chrome():
    m = re.search(r"\nQWidget\s*\{([^}]*)\}", VM_THEME_QSS)
    assert m, "there is no plain QWidget rule"
    body = m.group(1)
    for dark in ("vm_chrome", "vm_chrome_dark", "vm_rail", "vm_viewport"):
        assert THEME[dark] not in body, f"QWidget paints the {dark} token"
    assert THEME["bg_app"] in body
    # and it must carry the font, or unstyled widgets fall back to the platform default
    assert "font-family" in body and "font-size" in body


def test_selection_is_never_a_lone_amber_stroke():
    """Amber on the light canvas measures 1.0:1, so a selection pairs it with an edge."""
    assert THEME["accent_border"] != THEME["vm_accent"]
    # the deepened edge must clear the 3:1 non-text target on the card fill

    def srgb(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h):
        r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)

    a, b = lum(THEME["accent_border"]), lum(THEME["vm_node"])
    ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
    assert ratio >= 3.0, f"selection edge on a card is {ratio:.2f}:1"


def test_stylesheet_sources_have_no_literal_font_size_or_radius():
    """Font sizes and radii must come from the ramp so a change propagates everywhere.

    Checked in the *source* rather than the generated sheet: the template interpolates
    its tokens, so the rendered CSS necessarily contains resolved numbers and asserting
    on those would prove nothing.
    """
    for fname in ("styles.py", "vm_theme.py"):
        text = open(os.path.join(UI_DIR, fname), encoding="utf-8").read()
        fonts = re.findall(r"font-size:\s*\d+px", text)
        radii = re.findall(r"border-radius:\s*\d+px", text)
        assert not fonts, f"{fname} declares literal font sizes: {fonts[:5]}"
        assert not radii, f"{fname} declares literal radii: {radii[:5]}"


def test_stylesheet_sources_use_tokens_for_font_size_and_radius():
    """The obverse of the check above: the tokens must actually be used."""
    for fname in ("styles.py", "vm_theme.py"):
        text = open(os.path.join(UI_DIR, fname), encoding="utf-8").read()
        assert re.search(r"font-size:\s*\{", text), f"{fname} uses no size token"
        assert re.search(r"border-radius:\s*\{", text), f"{fname} uses no radius token"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    """A QApplication with the design-system font installed."""
    from PyQt6.QtWidgets import QApplication

    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    yield app
