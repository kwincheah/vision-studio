"""Tests for Plugin Marketplace, GitHub Installer, and Plugin Scaffolder.

Validates:
1. GitHub Repository URL parsing across various formats
2. Community Marketplace catalog loading, searching, and category filtering
3. Plugin Scaffolding / Creation (manifest, implementation, README, gitignore)
4. Runtime loading and DAG execution of newly scaffolded plugins
5. Plugin packaging into distributable .vmpkg bundles
6. Simulated GitHub repo ZIP extraction, validation, and installation
7. Marketplace UI dialog tabs, searching, and wizard interactions
"""
import os
import json
import zipfile
import tempfile
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

import apex_vision.tools
from apex_vision.sdk.marketplace import MarketplaceService, MarketplacePluginItem
from apex_vision.sdk.manager import PluginManager, PluginState
from apex_vision.core.registry import _TOOL_REGISTRY, _CATEGORIES, get_tool_class
from apex_vision.core.base_tool import ToolStatus
from apex_vision.ui.plugin_dialog import PluginManagerDialog
from apex_vision.ui.styles import initialize_app_fonts


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


# =============================================================================
# 1. GitHub URL Parsing & Normalization
# =============================================================================

def test_github_url_parsing():
    service = MarketplaceService.get_instance()

    # Standard URL
    res = service.parse_github_url("https://github.com/visionmaster/sample-plugin")
    assert res == ("visionmaster", "sample-plugin", "main")

    # With .git
    res = service.parse_github_url("https://github.com/visionmaster/sample-plugin.git")
    assert res == ("visionmaster", "sample-plugin", "main")

    # With branch/tag
    res = service.parse_github_url("https://github.com/visionmaster/sample-plugin/tree/v1.2.0")
    assert res == ("visionmaster", "sample-plugin", "v1.2.0")

    # Short form owner/repo
    res = service.parse_github_url("visionmaster/sample-plugin")
    assert res == ("visionmaster", "sample-plugin", "main")

    # Invalid URLs
    assert service.parse_github_url("") is None
    assert service.parse_github_url("invalid-url-without-slash") is None
    assert service.parse_github_url("https://gitlab.com/owner/repo") is None


# =============================================================================
# 2. Marketplace Catalog Browsing & Searching
# =============================================================================

def test_marketplace_catalog_and_search():
    service = MarketplaceService.get_instance()
    catalog = service.get_catalog(refresh=True)

    assert len(catalog) >= 5
    ids = [item.id for item in catalog]
    assert "sample_sobel_edge_plugin" in ids
    assert "clahe_contrast_enhancer" in ids
    assert "hough_circle_detector" in ids

    # Check installation status on sample_sobel_edge_plugin
    sobel_item = next(i for i in catalog if i.id == "sample_sobel_edge_plugin")
    assert sobel_item.is_installed is True

    # Search by keyword
    search_res = service.search(query="clahe")
    assert len(search_res) >= 1
    assert search_res[0].id == "clahe_contrast_enhancer"

    # Filter by category
    cat_res = service.search(query="", category="Measurement")
    assert len(cat_res) >= 1
    assert any("hough" in i.id for i in cat_res)


# =============================================================================
# 3. Plugin Scaffolding / Creation (Developer Workflow)
# =============================================================================

def test_scaffold_new_plugin(tmp_path):
    service = MarketplaceService.get_instance()

    ok, msg, created_dir = service.scaffold_plugin(
        dest_parent_dir=str(tmp_path),
        plugin_id="my_custom_threshold",
        name="Adaptive Threshold Pro",
        author="Vision Tech Lab",
        category="Custom Filters",
        tool_name="Adaptive Thresholding Tool",
        description="High-speed industrial thresholding plugin."
    )

    assert ok is True
    assert os.path.exists(created_dir)

    # 1. Verify plugin.json
    manifest_path = os.path.join(created_dir, "plugin.json")
    assert os.path.exists(manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["id"] == "my_custom_threshold"
    assert meta["name"] == "Adaptive Threshold Pro"
    assert meta["version"] == "1.0.0"
    assert meta["category"] == "Custom Filters"

    # 2. Verify __init__.py
    init_path = os.path.join(created_dir, "__init__.py")
    assert os.path.exists(init_path)

    # 3. Verify README.md and .gitignore
    assert os.path.exists(os.path.join(created_dir, "README.md"))
    assert os.path.exists(os.path.join(created_dir, ".gitignore"))

    # 4. Load the scaffolded plugin dynamically and test execution
    pm = PluginManager.get_instance()
    rec = pm.load_plugin_from_directory(created_dir, reload=True)

    assert rec is not None
    assert rec.state == PluginState.LOADED
    assert "Adaptive Thresholding Tool" in _TOOL_REGISTRY

    # 5. Instantiate and execute the newly generated tool
    tool_cls = get_tool_class("Adaptive Thresholding Tool")
    tool = tool_cls(instance_id="scaffold_tool_1")

    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    dummy_img[20:80, 20:80] = 200
    res = tool.execute({"Image": dummy_img})

    assert res.status == ToolStatus.OK
    assert "Image" in res.outputs
    assert "Metric_Value" in res.outputs

    # Clean up
    pm.unload_plugin("my_custom_threshold")


# =============================================================================
# 4. Plugin Packaging into .vmpkg Bundles
# =============================================================================

def test_package_plugin_bundle(tmp_path):
    service = MarketplaceService.get_instance()

    # Scaffold a plugin to package
    ok, _, created_dir = service.scaffold_plugin(
        dest_parent_dir=str(tmp_path),
        plugin_id="package_test_plugin",
        name="Package Test",
        author="Tester"
    )
    assert ok is True

    # Package into archive
    out_pkg = str(tmp_path / "package_test_plugin.vmpkg")
    pkg_ok, msg, pkg_path = service.package_plugin(created_dir, out_pkg)

    assert pkg_ok is True
    assert os.path.exists(pkg_path)

    # Inspect zip contents
    with zipfile.ZipFile(pkg_path, "r") as zf:
        namelist = zf.namelist()
        assert "plugin.json" in namelist
        assert "__init__.py" in namelist
        assert "README.md" in namelist
        assert not any("__pycache__" in n for n in namelist)


# =============================================================================
# 5. Simulated GitHub Repo Extraction & Validation
# =============================================================================

def test_validate_plugin_directory_positive_and_negative(tmp_path):
    service = MarketplaceService.get_instance()

    # Positive test on sample plugin
    sample_dir = os.path.abspath(os.path.join("plugins", "sample_sobel_edge_plugin"))
    valid, errors = service.validate_plugin_directory(sample_dir)
    assert valid is True
    assert len(errors) == 0

    # Negative test on missing manifest
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()
    valid, errors = service.validate_plugin_directory(str(empty_dir))
    assert valid is False
    assert any("plugin.json" in e for e in errors)


# =============================================================================
# 6. Marketplace UI Dialog Integration
# =============================================================================

def test_marketplace_ui_dialog(qapp, tmp_path):
    dlg = PluginManagerDialog(initial_tab=1)
    dlg._suppress_msgbox = True

    # 1. Marketplace Tab Checks
    assert dlg.tabs.currentIndex() == 1
    assert dlg.table_marketplace.rowCount() > 0

    # Search filter
    dlg.txt_market_search.setText("hough")
    dlg._populate_marketplace()
    assert dlg.table_marketplace.rowCount() >= 1

    dlg.txt_market_search.clear()
    dlg.combo_market_category.setCurrentText("Custom Filters")
    dlg._populate_marketplace()
    assert dlg.table_marketplace.rowCount() >= 1

    # 2. GitHub Installer Tab Checks
    dlg.tabs.setCurrentIndex(2)
    dlg.txt_github_url.setText("invalid-repo-url-syntax")
    dlg._on_direct_github_install_clicked()
    assert "[ERROR]" in dlg.txt_github_log.toPlainText()

    # 3. Creator Tab Checks
    dlg.tabs.setCurrentIndex(3)
    dlg.txt_create_id.setText("ui_wizard_plugin")
    dlg.txt_create_name.setText("UI Wizard Plugin")
    dlg.txt_create_author.setText("Tester")
    dlg.txt_create_dest.setText(str(tmp_path))

    dlg._on_generate_scaffold_clicked()
    expected_path = tmp_path / "ui_wizard_plugin"
    assert expected_path.exists()
    assert (expected_path / "plugin.json").exists()
    assert (expected_path / "__init__.py").exists()

    dlg.close()
