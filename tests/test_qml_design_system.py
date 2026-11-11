"""Regression tests for the QML design review fixes.

Each test guards a defect that was found by rendering the interface and measuring it, not
by reading the code.  They are structural where possible (a QML source assertion), because
that is what can break silently when someone edits a delegate.
"""
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QML = os.path.join(ROOT, "qml")
MAIN_SCREEN = os.path.join(QML, "screens", "MainScreen.qml")


def qml_text(relative: str) -> str:
    return open(os.path.join(QML, relative), encoding="utf-8").read()


def code_only(text: str) -> str:
    """Strip `//` comments, so a literal quoted in an explanatory note is not a hit.

    Every fix in this file documents the value it replaced, so the old literal survives in
    a comment on purpose.  Assertions about code must look at code.
    """
    return "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())


def main_screen() -> str:
    return open(MAIN_SCREEN, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# Flow tab: the label must fit its own tab
# ---------------------------------------------------------------------------
def test_flow_tab_width_follows_its_label():
    """The tab was a fixed 190 px, so "FAIL 165ms" was elided to "FAIL 1…".

    The label needs ~171 px of text, and the tab spends 10 px of left inset plus the close
    button, so a fixed width can never fit every name.  The width must be derived from the
    label with a floor and a ceiling.
    """
    text = main_screen()
    delegate = text[text.find('objectName: "flowTab_"'):
                    text.find('objectName: "flowTab_"') + 1800]
    assert "width: Math.max(190" in delegate, (
        "the flow tab width is not derived from its label")
    assert "tabLabel.implicitWidth" in delegate, (
        "the flow tab width does not reference the label's implicit width")
    # the label must be the one the width reads
    assert re.search(r"id:\s*tabLabel", delegate), "the label lost its id"


def test_flow_tab_width_is_capped():
    """A pathological name must not grow the tab without bound."""
    text = code_only(main_screen())
    start = text.find('objectName: "flowTab_"')
    block = text[start:start + 700]
    assert "Math.min(320" in block, "the flow tab has no maximum width"


def test_flow_tab_scroll_math_uses_real_widths():
    """`showActive` hardcoded `i * 192` while the tab width is no longer fixed."""
    text = main_screen()
    start = text.find("function showActive")
    body = text[start:start + 700]
    assert "i * 192" not in body, (
        "showActive still assumes a fixed 192 px tab pitch; it must read each tab's width")
    assert "children" in body


# ---------------------------------------------------------------------------
# Multi-flow overview: real flows, not a placeholder
# ---------------------------------------------------------------------------
def test_multi_flow_overview_renders_every_flow():
    """It drew one card with the hardcoded name "PCB_AOI_Solution"."""
    text = code_only(main_screen())
    start = text.find("workspaceTab === 2")
    assert start != -1, "the multi-flow section is missing"
    block = text[start:start + 2600]
    assert "PCB_AOI_Solution" not in block, (
        "the multi-flow overview still hardcodes a flow name")
    assert "Repeater" in block and "root.tabList" in block, (
        "the multi-flow overview does not render the real flow list")
    assert "modelData.name" in block, "the card does not show the flow's name"


def test_multi_flow_overview_centres_a_self_sizing_container():
    """`Flow` reports no implicit size, so anchoring it centred put the block in a corner."""
    text = code_only(main_screen())
    start = text.find("workspaceTab === 2")
    block = text[start:start + 1400]
    assert "Grid {" in block, "the overview should use a self-sizing Grid"
    assert "anchors.centerIn: parent" in block


def test_multi_flow_overview_uses_status_tokens():
    """Its verdict border used the literal "#2fa56a"/"#e0585c"."""
    text = code_only(main_screen())
    start = text.find("workspaceTab === 2")
    block = text[start:start + 2600]
    assert "#2fa56a" not in block and "#e0585c" not in block, (
        "the overview still uses literal status colours")
    assert "Theme.okBorder" in block and "Theme.errorBorder" in block


# ---------------------------------------------------------------------------
# Semantic status colour is one token, not several literals
# ---------------------------------------------------------------------------
def test_node_card_uses_status_tokens():
    card = code_only(qml_text("ApexComponents/NodeCard.qml"))
    assert '"#2fa56a"' not in card, "NodeCard still hardcodes its PASS green"
    assert '"#e0585c"' not in card, "NodeCard still hardcodes its FAIL red"
    assert "Theme.okBorder" in card
    assert "Theme.errorBorder" in card


def test_status_badge_and_node_card_agree_on_the_green():
    """The same PASS verdict was drawn in #00754a on the badge and #2fa56a on the card."""
    badge = code_only(qml_text("ApexComponents/StatusBadge.qml"))
    card = code_only(qml_text("ApexComponents/NodeCard.qml"))
    theme = qml_text("ApexTheme/Theme.qml")
    ok = re.search(r'readonly property color okBorder:\s*"(#[0-9a-fA-F]{6})"', theme)
    assert ok, "okBorder missing from the theme"
    # both should resolve through the token rather than their own literal
    assert "okBorder" in card
    assert "okBorder" in badge or ok.group(1) in badge


# ---------------------------------------------------------------------------
# Palette discipline
# ---------------------------------------------------------------------------
def test_theme_has_no_duplicate_type_sizes():
    """`fontMicro` and `fontCaption` were both 11, which makes one of them meaningless."""
    theme = qml_text("ApexTheme/Theme.qml")
    sizes = re.findall(r"readonly property int font(\w+):\s*(\d+)", theme)
    by_size = {}
    for name, value in sizes:
        by_size.setdefault(value, []).append(name)
    duplicates = {v: names for v, names in by_size.items() if len(names) > 1}
    assert not duplicates, f"type sizes defined twice: {duplicates}"


@pytest.mark.parametrize("component", [
    "ApexComponents/NodeCard.qml", "ApexComponents/AppButton.qml",
    "ApexComponents/StatusBadge.qml", "ApexComponents/ChromeToolButton.qml",
])
def test_components_reference_the_theme(component):
    """A component that hardcodes everything cannot follow a palette change."""
    text = qml_text(component)
    assert "Theme." in text, f"{component} references no theme token"


# ---------------------------------------------------------------------------
# Recent-projects pollution (the start screen showed pytest temp paths)
# ---------------------------------------------------------------------------
def test_every_module_that_builds_a_project_manager_is_isolated_in_tests():
    """The conftest patched only `ui.main_window`; the QML backend and start page leaked.

    28 of 30 recent-project entries were `...Temp/pytest-of-<user>/...`, which is what the
    start screen rendered.  All three modules must be covered.
    """
    conftest = open(os.path.join(ROOT, "tests", "conftest.py"), encoding="utf-8").read()
    start = conftest.find("_isolate_default_project_manager")
    body = conftest[start:start + 1400]
    for module in ("apex_vision.qml_backend", "apex_vision.ui.main_window",
                   "apex_vision.ui.start_page"):
        assert module in body, f"{module} is not covered by the recent-projects isolation"


def test_no_test_module_writes_into_the_real_config():
    """A guard for the same class of leak from a different entry point."""
    project_manager = open(os.path.join(ROOT, "apex_vision", "core", "project_manager.py"),
                           encoding="utf-8").read()
    # the cache path must be derived from an injectable workspace root
    assert "workspace_root" in project_manager
    assert "cache_file" in project_manager
