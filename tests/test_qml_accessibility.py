"""Regression tests for the accessibility and layout defects found in the design audit.

Every case here was found by rendering the interface and measuring it — overflow,
contrast, Tab traversal — not by reading the source.  They are structural assertions where
a runtime check would need a display, and behavioural where one is cheap.
"""
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QML = os.path.join(ROOT, "qml")


def qml(rel: str) -> str:
    return open(os.path.join(QML, rel), encoding="utf-8").read()


def code(rel: str) -> str:
    """Source with `//` comments removed, so literals quoted in notes are not hits."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in qml(rel).splitlines())


def theme() -> dict:
    text = qml("ApexTheme/Theme.qml")
    return {m.group(1): m.group(2).lower()
            for m in re.finditer(r'readonly property color (\w+)\s*:\s*"(#[0-9a-fA-F]{6})"',
                                 text)}


# ---------------------------------------------------------------------------
# Keyboard access
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("component", ["TextBox", "NumberBox"])
def test_input_components_are_in_the_tab_chain(component):
    """TextInput does not join the Tab chain unless it opts in.

    In Flow Settings, Tab went CheckLabel -> Cancel -> OK and skipped both numeric
    fields, so a keyboard-only operator could not change the run interval at all.
    """
    text = code("ApexComponents/%s.qml" % component)
    assert "activeFocusOnTab" in text, (
        f"{component}'s TextInput cannot be reached with Tab")


def test_tab_button_is_focusable_and_draws_a_ring():
    """Workspace tabs are controls; they were not in the Tab chain at all."""
    text = code("ApexComponents/TabButton2.qml")
    assert "activeFocusOnTab: true" in text
    assert "activeFocus" in text, "a focusable tab with no focus indicator"
    assert "Keys.onPressed" in text, "a focusable tab that Enter/Space cannot activate"


@pytest.mark.parametrize("component", [
    "AppButton", "ChromeToolButton", "ChromePillButton", "TextBox", "SelectBox",
    "NumberBox", "CheckLabel", "ToggleSwitch", "TabButton2", "ModelPicker",
])
def test_every_interactive_component_is_focusable_with_a_ring(component):
    text = code("ApexComponents/%s.qml" % component)
    assert "activeFocusOnTab" in text, f"{component} is not keyboard reachable"
    assert "activeFocus" in text, f"{component} draws no focus ring"


# ---------------------------------------------------------------------------
# Focus-ring contrast
# ---------------------------------------------------------------------------
def _srgb(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(h):
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_focus_ring_on_chrome_is_not_the_blue_primary():
    """Blue `primary` on chromeDark is 1.11:1 - an invisible focus ring.

    The toolbar and rail therefore use a dedicated light ring token.
    """
    colours = theme()
    assert "focusOnChrome" in colours, "no light ring token for the dark chrome"
    assert _contrast(colours["focusOnChrome"], colours["chromeDark"]) >= 3.0
    assert _contrast(colours["focusOnChrome"], colours["rail"]) >= 3.0
    # and the blue really is unusable there, which is why the token exists
    assert _contrast(colours["primary"], colours["chromeDark"]) < 3.0


@pytest.mark.parametrize("component", ["ChromeToolButton", "ChromePillButton"])
def test_chrome_components_use_the_light_ring(component):
    text = code("ApexComponents/%s.qml" % component)
    assert "Theme.focusOnChrome" in text, (
        f"{component} draws its focus ring in a colour that is invisible on the chrome")


# ---------------------------------------------------------------------------
# Filled-button contrast, including hover
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("token", ["runGreen", "runGreenHover", "stopRed", "stopRedHover",
                                   "primary", "primaryHover", "okBorder", "errorBorder"])
def test_white_text_on_a_filled_button_clears_aa(token):
    """Hover fills are chosen for hue by eye and drifted below 4.5:1 with white text.

    `runGreenHover` was #16a34a at 3.30:1 and `primaryHover` #0a89c4 at 3.90:1.
    """
    colours = theme()
    assert token in colours, f"{token} missing from the theme"
    ratio = _contrast("#ffffff", colours[token])
    assert ratio >= 4.5, f"white on {token} is {ratio:.2f}:1"


# ---------------------------------------------------------------------------
# Dialog layout
# ---------------------------------------------------------------------------
def test_dialog_frame_card_is_addressable():
    """Every dialog fills the host, so without a named card an audit cannot measure it."""
    text = code("ApexComponents/DialogFrame.qml")
    assert 'objectName: "dialogFrame"' in text
    assert 'objectName: "dialogCard"' in text


def test_global_variables_add_row_fits_the_dialog():
    """The row was 628 px (604 + 3 x 8 spacing) inside a 608 px body.

    "+ Add Variable" therefore ended 4 px past the dialog's right edge and was clipped.
    The fields must be flexible rather than fixed.
    """
    text = code("ApexDialogs/GlobalVariablesDialog.qml")
    start = text.find("id: addRow")
    assert start != -1, "the add-variable row lost its id"
    block = text[start:start + 1400]
    fixed = re.findall(r"width:\s*(\d{2,3})\s*[;}]", block)
    # the button keeps a fixed width; the three fields must not
    assert len(fixed) <= 1, (
        f"the add row still hardcodes field widths: {fixed}")
    assert "addRow.width" in block, (
        "the fields do not derive their width from the row")


def test_tab_button_accounts_for_its_border():
    """`implicitWidth` omitted the 1 px border on each side.

    The tab then came out exactly as wide as its text plus padding, so a bold (selected)
    label lost its last pixel - "Create & Publish" rendered clipped in the Plugin Manager.
    """
    text = code("ApexComponents/TabButton2.qml")
    m = re.search(r"implicitWidth:\s*label\.implicitWidth \+ ([^;\n]+)", text)
    assert m, "the tab width formula is missing"
    terms = m.group(1)
    assert "+ 2 +" in terms or "+ 2;" in terms, (
        f"the tab width does not include its 2 px of border: {terms.strip()!r}")


def test_validation_message_is_grammatical():
    """It read "1 issue(s) need attention."."""
    text = code("ApexDialogs/ValidationDialog.qml")
    assert "issue(s)" not in text, 'the plural form is still baked in as "issue(s)"'
    assert "1 issue needs attention" in text
    assert "issues need attention" in text


# ---------------------------------------------------------------------------
# Palette discipline for the pieces that were promoted
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("token", ["runFillDark", "runFillDarkHover", "stopFillDark",
                                   "stopFillDarkHover", "chromeDivider", "portHot",
                                   "focusOnChrome"])
def test_promoted_tokens_exist(token):
    assert token in theme(), f"{token} is not a theme token"


@pytest.mark.parametrize("value", ['"#15351f"', '"#1d4d2e"', '"#3b181c"', '"#5a242a"'])
def test_icon_button_fills_are_tokenised(value):
    text = code("ApexComponents/ChromeToolButton.qml")
    assert value not in text, f"{value} is still a literal in the component"


def test_theme_has_no_duplicate_type_sizes():
    text = qml("ApexTheme/Theme.qml")
    sizes = re.findall(r"readonly property int font(\w+):\s*(\d+)", text)
    by_size = {}
    for name, value in sizes:
        by_size.setdefault(value, []).append(name)
    dupes = {v: n for v, n in by_size.items() if len(n) > 1}
    assert not dupes, f"type sizes defined twice: {dupes}"


#: Token pairs that deliberately share a value because they carry different *roles*.
#: `primaryText` and `wire` are both the primary blue by design (a wire is drawn in the
#: primary colour); `focusOnChrome` and `fieldBg` are both white for unrelated reasons (a
#: light ring on dark chrome, and an input's white well).
ALLOWED_ALIASES = {
    frozenset({"primaryText", "wire"}),
    frozenset({"focusOnChrome", "fieldBg"}),
    # keywords are drawn in the brand blue on purpose: the eye should read `def`/`return`
    # as the same family as the rest of the interface
    frozenset({"primaryText", "wire", "syntaxKeyword"}),
}


def test_theme_has_no_duplicate_colour_values():
    """A colour defined twice under two names makes one of the names meaningless.

    Genuine semantic aliases are listed above; anything else is an accident.
    """
    colours = theme()
    by_value = {}
    for name, value in colours.items():
        by_value.setdefault(value, []).append(name)
    dupes = {}
    for value, names in by_value.items():
        if len(names) > 1 and frozenset(names) not in ALLOWED_ALIASES:
            dupes[value] = names
    assert not dupes, f"colours defined more than once: {dupes}"
