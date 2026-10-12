"""
Tests for UI Icons, Theme Tokens, and Tool Navigation polish.
"""
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from vm_clone.ui.icons import get_category_icon, get_tool_icon, get_action_icon
from vm_clone.ui.styles import THEME, INDUSTRIAL_THEME_QSS
from vm_clone.core.registry import list_categories, get_tool_class
from vm_clone.ui.main_window import VisionMasterMainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_theme_tokens_complete():
    """Verify that all core design tokens are defined and adhere to industrial specs."""
    required_keys = [
        "bg_app", "bg_surface", "bg_control", "border_subtle", "border_control",
        "text_primary", "text_secondary", "text_muted", "accent_primary",
        "status_ok_text", "status_warn_text", "status_error_text", "status_running_text"
    ]
    for key in required_keys:
        assert key in THEME, f"Missing required theme token: {key}"
        assert isinstance(THEME[key], str) and THEME[key].startswith("#")

    # Palette constraints: ensure accent is steel/engineering blue
    assert THEME["accent_primary"] in ("#3b82f6", "#2563eb", "#4a90e2")
    # Verify stylesheet is formatted with theme
    assert THEME["bg_app"] in INDUSTRIAL_THEME_QSS


def test_category_icons_rendered(qapp):
    """Verify that every machine vision category produces a valid non-empty vector icon."""
    categories = list_categories()
    assert len(categories) >= 10

    for cat_name in categories.keys():
        icon = get_category_icon(cat_name)
        assert isinstance(icon, QIcon)
        assert not icon.isNull(), f"Category icon for '{cat_name}' is null"
        pix = icon.pixmap(16, 16)
        assert not pix.isNull()
        assert pix.width() == 16 and pix.height() == 16


def test_tool_icons_rendered(qapp):
    """Verify that each registered tool produces a valid vector icon."""
    categories = list_categories()
    total_tools = 0

    for cat_name, tools in categories.items():
        for tool_name in tools:
            total_tools += 1
            icon = get_tool_icon(tool_name)
            assert isinstance(icon, QIcon)
            assert not icon.isNull(), f"Tool icon for '{tool_name}' is null"
            pix = icon.pixmap(16, 16)
            assert not pix.isNull()
            assert pix.width() == 16 and pix.height() == 16

    assert total_tools >= 30, f"Expected >= 30 tools, found {total_tools}"


def test_toolbar_action_icons(qapp):
    """Verify that all command toolbar actions have functional vector icons."""
    actions = [
        "run_once", "run_all", "continuous", "stop", "fit",
        "zoom_100", "draw_roi", "histogram", "layers", "arrange", "add_flow"
    ]
    for act in actions:
        icon = get_action_icon(act)
        assert isinstance(icon, QIcon)
        assert not icon.isNull(), f"Action icon for '{act}' is null"
        pix = icon.pixmap(16, 16)
        assert not pix.isNull()


def test_main_window_tool_tree_icons_and_tooltips(qapp):
    """Verify that MainWindow initializes the tool tree with icons and informative tooltips."""
    win = VisionMasterMainWindow()
    tree = win.tool_tree
    assert tree.topLevelItemCount() > 0

    for i in range(tree.topLevelItemCount()):
        cat_item = tree.topLevelItem(i)
        assert not cat_item.icon(0).isNull(), f"Category item '{cat_item.text(0)}' missing icon"

        for j in range(cat_item.childCount()):
            tool_item = cat_item.child(j)
            assert not tool_item.icon(0).isNull(), f"Tool item '{tool_item.text(0)}' missing icon"
            tooltip = tool_item.toolTip(0)
            assert len(tooltip) > 0, f"Tool item '{tool_item.text(0)}' missing tooltip"
            assert tool_item.text(0).strip() in tooltip

    # Verify buttons have icons
    assert not win.btn_run_once.icon().isNull()
    assert not win.btn_flow_once.icon().isNull()
    assert not win.btn_continuous.icon().isNull()
    assert not win.btn_stop.icon().isNull()
    assert not win.btn_draw_roi.icon().isNull()
    assert not win.btn_hist.icon().isNull()
    assert not win.btn_layers.icon().isNull()
    assert not win.btn_add_flow.icon().isNull()
    win.close()
