"""Contrast and readability regression tests.

These lock in the audit results so a later palette or stylesheet edit cannot
silently reintroduce an unreadable surface.  Everything asserted here was measured
from a rendered capture or from the generated stylesheet - see
`docs/UI_POLISH_AUDIT.md` for the findings these tests guard.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vm_clone.ui.styles import THEME  # noqa: E402
from vm_clone.ui.vm_theme import VM_THEME_QSS  # noqa: E402


# ---------------------------------------------------------------------------
# WCAG helpers
# ---------------------------------------------------------------------------
def _srgb(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexcol: str) -> float:
    """Relative luminance on the 0-255 scale, matching `luminance` helpers."""
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return 255.0 * (0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b))


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------------------
# Palette-level pairs
# ---------------------------------------------------------------------------
#: (label, foreground token, background token, minimum ratio)
TEXT_PAIRS = [
    ("body on panel", "text_primary", "bg_surface"),
    ("body on window field", "text_primary", "bg_app"),
    ("body on card", "text_primary", "bg_surface_alt"),
    ("body on module card", "vm_node_text", "vm_node"),
    ("secondary on panel", "text_secondary", "bg_surface"),
    ("muted on panel", "text_muted", "bg_surface"),
    ("muted on card", "text_muted", "bg_surface_alt"),
    ("muted on window field", "text_muted", "bg_app"),
    ("card dim ink on card", "vm_node_text_dim", "vm_node"),
    ("ink on table header", "text_primary", "vm_panel_header"),
    ("menu ink on menu strip", "text_on_menu", "vm_chrome"),
    ("chrome ink on toolbar", "text_on_chrome", "vm_chrome_dark"),
    ("body on control face", "text_primary", "bg_control"),
    ("secondary on control face", "text_secondary", "bg_control"),
    ("viewport ink on viewport", "vm_viewport_text", "vm_viewport"),
    ("ink on amber selection wash", "text_primary", "accent_dim"),
    ("OK ink on OK wash", "status_ok_text", "status_ok_bg"),
    ("warn ink on warn wash", "status_warn_text", "status_warn_bg"),
    ("error ink on error wash", "status_error_text", "status_error_bg"),
    ("running ink on run wash", "status_running_text", "status_running_bg"),
]

#: Non-text UI: borders and state indicators, WCAG 1.4.11 (3:1).
UI_PAIRS = [
    ("border vs panel", "border_subtle", "bg_surface"),
    ("control border vs control face", "border_control", "bg_control"),
    ("card border vs canvas", "vm_node_border", "vm_canvas"),
    ("selection edge vs card", "accent_border", "vm_node"),
    ("wire vs canvas", "vm_wire", "vm_canvas"),
    ("OK border vs panel", "status_ok_border", "bg_surface"),
    ("warn border vs panel", "status_warn_border", "bg_surface"),
    ("error border vs panel", "status_error_border", "bg_surface"),
    ("run border vs panel", "status_running_border", "bg_surface"),
    ("rail vs panel", "vm_rail", "bg_surface"),
    ("focus ring vs panel", "border_focus", "bg_surface"),
]


@pytest.mark.parametrize("label,fg,bg", TEXT_PAIRS)
def test_text_pairs_meet_wcag_aa(label, fg, bg):
    """Normal text must reach 4.5:1 on the surface it is drawn on."""
    r = contrast(THEME[fg], THEME[bg])
    assert r >= 4.5, f"{label}: {THEME[fg]} on {THEME[bg]} = {r:.2f}:1 (need 4.5)"


@pytest.mark.parametrize("label,fg,bg", UI_PAIRS)
def test_ui_pairs_meet_wcag_non_text(label, fg, bg):
    """Borders and state indicators must reach 3:1 against their surround."""
    r = contrast(THEME[fg], THEME[bg])
    assert r >= 3.0, f"{label}: {THEME[fg]} on {THEME[bg]} = {r:.2f}:1 (need 3.0)"


# ---------------------------------------------------------------------------
# Stylesheet-level checks
# ---------------------------------------------------------------------------
#: Selectors that must not pair dark ink with the dark chrome surfaces.
DARK_SURFACES = ("vm_chrome", "vm_chrome_dark", "vm_rail", "vm_viewport")
LIGHT_INK = ("text_on_chrome", "text_on_menu")


def test_no_rule_puts_dark_ink_on_dark_chrome():
    """A rule that paints a dark surface must use light ink on it.

    This is the class of bug the audit found: the palette was converted to a light
    theme, but rules that paint the steel chrome kept the (now dark) body ink, which
    made the status bar and the flow tab labels effectively invisible.
    """
    surface_hexes = {THEME[k] for k in DARK_SURFACES}
    offenders = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", VM_THEME_QSS, re.S):
        sel = " ".join(m.group(1).split())
        body = m.group(2)
        bg = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", body)
        fg = re.search(r"(?<!-)\bcolor:\s*(#[0-9a-fA-F]{6})", body)
        if not (bg and fg):
            continue
        if bg.group(1) not in surface_hexes:
            continue
        if contrast(fg.group(1), bg.group(1)) < 4.5:
            offenders.append(f"{sel[:50]} -> {fg.group(1)} on {bg.group(1)}")
    assert not offenders, "dark ink on dark chrome:\n  " + "\n  ".join(offenders)


def test_input_widgets_are_light_wells():
    """Inputs must use a light base, not a chrome grey."""
    for selector in ("QSpinBox, QDoubleSpinBox, QComboBox",):
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", VM_THEME_QSS, re.S)
        assert m, f"{selector} rule missing"
        body = m.group(1)
        bg = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", body).group(1)
        fg = re.search(r"(?<!-)\bcolor:\s*(#[0-9a-fA-F]{6})", body).group(1)
        assert contrast(fg, bg) >= 4.5, f"{selector}: {fg} on {bg}"
        # The well must be lighter than its own border, i.e. a real sunken field.
        border = re.search(r"border:\s*1px solid\s*(#[0-9a-fA-F]{6})", body)
        if border:
            assert _lum(bg) > _lum(border.group(1))


def test_global_widget_rule_is_not_chrome():
    """The catch-all QWidget rule must not paint the chrome colour.

    A generic rule with a dark fill makes every unstyled container - tooltips
    included - dark, which is what put dark text on a dark field.
    """
    m = re.search(r"\nQWidget\s*\{([^}]*)\}", VM_THEME_QSS)
    assert m, "no plain QWidget rule found"
    bg = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", m.group(1)).group(1)
    for k in DARK_SURFACES:
        assert bg != THEME[k], f"QWidget background is the chrome token {k}"


def test_tooltip_and_dialog_are_light_and_readable():
    """Tooltips and dialogs must be light surfaces with dark ink."""
    for selector in ("QToolTip", "QDialog"):
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", VM_THEME_QSS, re.S)
        assert m, f"{selector} rule missing"
        body = m.group(1)
        bg = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", body).group(1)
        fg = re.search(r"(?<!-)\bcolor:\s*(#[0-9a-fA-F]{6})", body).group(1)
        assert _lum(bg) > 150, f"{selector} background {bg} is not a light surface"
        assert contrast(fg, bg) >= 4.5, f"{selector}: {fg} on {bg}"


def test_every_literal_pair_in_the_stylesheet_is_readable():
    """Sweep the whole generated sheet for an unreadable colour/background pair."""
    offenders = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", VM_THEME_QSS, re.S):
        sel = " ".join(m.group(1).split())
        if sel.startswith("/*") or not sel:
            continue
        body = m.group(2)
        bg = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", body)
        fg = re.search(r"(?<!-)\bcolor:\s*(#[0-9a-fA-F]{6})", body)
        if not (bg and fg):
            continue
        size = re.search(r"font-size:\s*(\d+)px", body)
        need = 3.0 if size and int(size.group(1)) >= 18 else 4.5
        r = contrast(fg.group(1), bg.group(1))
        if r < need:
            offenders.append(f"{sel[:52]} -> {fg.group(1)} on {bg.group(1)} "
                             f"= {r:.2f} (need {need})")
    assert not offenders, "unreadable stylesheet pairs:\n  " + "\n  ".join(offenders)
