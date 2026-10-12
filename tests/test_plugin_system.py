"""Automated Tests for Vision Master Clone Plugin Architecture & SDK.

Verifies:
1. SemVer parsing & compatibility rules (exact, caret ^, >=, <=, ==)
2. Parameter Schema (ParamDef) type safety, range checks, and enum validation
3. PluginMetadata validation (id, semver, min_sdk_version)
4. PluginManager discovery and dynamic loading from directory
5. Sample third-party Sobel Edge plugin discovery, registration, and DAG execution
6. Incompatible SDK version rejection
7. Malformed manifest and missing entrypoint error handling
8. Dynamic plugin unloading and registry cleanup
9. Workflow persistence (save/load) containing third-party plugin tools
10. Untrusted execution exception containment (no host crash on faulty plugin execution)
"""
import os
import json
import shutil
import tempfile
import pytest
import numpy as np

import vm_clone.tools
from vm_clone.sdk import (
    PluginMetadata,
    ParamDef,
    ParamType,
    CURRENT_SDK_VERSION,
    parse_semver,
    is_version_compatible,
    PluginToolBase,
    IVisionPlugin
)
from vm_clone.sdk.manager import PluginManager, PluginState
from vm_clone.core.base_tool import DataType, ToolStatus, ToolPort, ToolExecutionResult
from vm_clone.core.pipeline import VisionPipeline
from vm_clone.core.registry import _TOOL_REGISTRY, _CATEGORIES, get_tool_class, unregister_tool


# --- 1. SemVer & Version Compatibility Tests ---

def test_semver_parsing_valid():
    assert parse_semver("1.0.0") == (1, 0, 0)
    assert parse_semver("2.14.3") == (2, 14, 3)
    assert parse_semver("0.1.0-alpha") == (0, 1, 0)
    assert parse_semver("1.0.0+build123") == (1, 0, 0)


def test_semver_parsing_invalid():
    with pytest.raises(ValueError):
        parse_semver("v1.0")
    with pytest.raises(ValueError):
        parse_semver("1.0")
    with pytest.raises(ValueError):
        parse_semver("invalid")


def test_is_version_compatible():
    assert is_version_compatible(">=1.0.0", "1.0.0")
    assert is_version_compatible(">=1.0.0", "1.2.0")
    assert not is_version_compatible(">=2.0.0", "1.5.0")
    assert is_version_compatible("^1.0.0", "1.3.4")
    assert not is_version_compatible("^1.0.0", "2.0.0")
    assert is_version_compatible("==1.2.3", "1.2.3")
    assert not is_version_compatible("==1.2.3", "1.2.4")
    assert is_version_compatible("*", "3.0.0")


# --- 2. ParamDef Validation Tests ---

def test_param_def_int_validation():
    param = ParamDef(name="ksize", param_type=ParamType.INT, default_value=3, min_value=1, max_value=7)
    valid, _ = param.validate(5)
    assert valid is True
    valid, msg = param.validate(9)
    assert valid is False and "greater than max" in msg
    valid, msg = param.validate("not_an_int")
    assert valid is False


def test_param_def_enum_validation():
    param = ParamDef(name="direction", param_type=ParamType.ENUM, default_value="Both", choices=["Both", "Horizontal", "Vertical"])
    assert param.validate("Both")[0] is True
    assert param.validate("Horizontal")[0] is True
    valid, msg = param.validate("Diagonal")
    assert valid is False and "valid choices" in msg


def test_param_def_roi_validation():
    param = ParamDef(name="roi", param_type=ParamType.ROI, default_value=[0, 0, 100, 100])
    assert param.validate([10, 20, 50, 50])[0] is True
    valid, _ = param.validate([10, 20])
    assert valid is False


# --- 3. PluginMetadata Validation Tests ---

def test_metadata_validation():
    valid_meta = PluginMetadata(
        plugin_id="valid_plugin_1",
        name="Valid Plugin",
        version="1.0.0",
        author="Tester",
        min_sdk_version="1.0.0"
    )
    assert len(valid_meta.validate()) == 0

    invalid_meta = PluginMetadata(
        plugin_id="invalid plugin with spaces!",
        name="",
        version="not_semver",
        author="Tester",
        min_sdk_version="bad"
    )
    errors = invalid_meta.validate()
    assert len(errors) >= 3


# --- 4. Sample Third-Party Plugin Discovery & Loading ---

def test_discover_and_load_sample_sobel_plugin():
    manager = PluginManager(plugin_dirs=[os.path.abspath("plugins")])
    plugins = manager.discover_and_load_all()

    assert "sample_sobel_edge_plugin" in plugins
    record = plugins["sample_sobel_edge_plugin"]
    assert record.state == PluginState.LOADED
    assert record.metadata.name == "Sobel Edge Detector"
    assert record.metadata.version == "1.0.0"
    assert record.metadata.category == "Custom Filters"
    assert len(record.tools) == 1

    tool_cls = record.tools[0]
    assert tool_cls.tool_name == "Sobel Edge Detector"
    assert tool_cls.category == "Custom Filters"
    assert "Sobel Edge Detector" in _TOOL_REGISTRY
    assert "Custom Filters" in _CATEGORIES
    assert "Sobel Edge Detector" in _CATEGORIES["Custom Filters"]


# --- 5. Tool Execution & Pipeline DAG Integration ---

def test_sobel_plugin_tool_execution():
    tool_cls = get_tool_class("Sobel Edge Detector")
    tool = tool_cls(instance_id="sobel_1")

    # Create dummy 100x100 gradient image
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:, 50:] = 255  # Distinct vertical step edge

    context = {"Image": img}
    result = tool.execute(context)

    assert result.status == ToolStatus.OK
    assert "Image" in result.outputs
    assert "Edge_Intensity" in result.outputs
    assert isinstance(result.outputs["Image"], np.ndarray)
    assert result.outputs["Image"].shape == (100, 100, 3)
    assert result.outputs["Edge_Intensity"] > 0.0


def test_sobel_tool_in_vision_pipeline():
    pipeline = VisionPipeline()

    # Step 1: Create Image Source tool
    src_cls = get_tool_class("Image Source")
    src_tool = src_cls(instance_id="src_node", name="Source Step")
    pipeline.add_node(src_tool)

    # Step 2: Create Sobel tool instance
    tool_cls = get_tool_class("Sobel Edge Detector")
    sobel_tool = tool_cls(instance_id="sobel_node", name="Sobel Step")
    pipeline.add_node(sobel_tool)

    # Step 3: Connect src.Image -> sobel.Image
    connected = pipeline.connect("src_node", "Image", "sobel_node", "Image")
    assert connected is True

    # Step 4: Execute flow
    results = pipeline.execute_flow()
    assert "src_node" in results
    assert results["src_node"].status == ToolStatus.OK
    assert "sobel_node" in results
    assert results["sobel_node"].status == ToolStatus.OK
    out_img = results["sobel_node"].outputs["Image"]
    assert out_img is not None
    assert np.max(out_img) > 0
    assert results["sobel_node"].outputs["Edge_Intensity"] > 0


# --- 6. Incompatible SDK Version Handling ---

def test_incompatible_sdk_version_handling(tmp_path):
    incompat_dir = tmp_path / "incompat_plugin"
    incompat_dir.mkdir()

    manifest = {
        "id": "incompat_plugin",
        "name": "Future Plugin",
        "version": "1.0.0",
        "author": "Time Traveler",
        "min_sdk_version": "99.0.0",
        "entrypoint": "__init__.py"
    }
    (incompat_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (incompat_dir / "__init__.py").write_text("# empty\n", encoding="utf-8")

    manager = PluginManager(plugin_dirs=[str(tmp_path)])
    record = manager.load_plugin_from_directory(str(incompat_dir))

    assert record is not None
    assert record.state == PluginState.INCOMPATIBLE
    assert "SDK version mismatch" in record.error_message


# --- 7. Malformed Manifest Handling ---

def test_malformed_manifest_handling(tmp_path):
    bad_dir = tmp_path / "bad_manifest_plugin"
    bad_dir.mkdir()

    # Malformed JSON
    (bad_dir / "plugin.json").write_text("{ unclosed json: ", encoding="utf-8")

    manager = PluginManager(plugin_dirs=[str(tmp_path)])
    record = manager.load_plugin_from_directory(str(bad_dir))

    assert record is not None
    assert record.state == PluginState.ERROR
    assert "Manifest parse error" in record.error_message


# --- 8. Missing Entrypoint Handling ---

def test_missing_entrypoint_handling(tmp_path):
    missing_dir = tmp_path / "missing_entry_plugin"
    missing_dir.mkdir()

    manifest = {
        "id": "missing_entry_plugin",
        "name": "Missing Entry",
        "version": "1.0.0",
        "min_sdk_version": "1.0.0",
        "entrypoint": "non_existent.py"
    }
    (missing_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

    manager = PluginManager(plugin_dirs=[str(tmp_path)])
    record = manager.load_plugin_from_directory(str(missing_dir))

    assert record is not None
    assert record.state == PluginState.ERROR
    assert "Entrypoint file 'non_existent.py' not found" in record.error_message


# --- 9. Dynamic Unload & Registry Cleanup ---

def test_dynamic_unload_plugin():
    manager = PluginManager.get_instance()
    # Ensure sample plugin is loaded
    manager.add_plugin_dir(os.path.abspath("plugins"))
    manager.discover_and_load_all()

    assert "sample_sobel_edge_plugin" in manager._plugins
    assert "Sobel Edge Detector" in _TOOL_REGISTRY

    # Unload plugin
    success = manager.unload_plugin("sample_sobel_edge_plugin")
    assert success is True
    assert "sample_sobel_edge_plugin" not in manager._plugins
    assert "Sobel Edge Detector" not in _TOOL_REGISTRY
    assert "Custom Filters" not in _CATEGORIES or "Sobel Edge Detector" not in _CATEGORIES.get("Custom Filters", [])

    # Reload to keep environment restored
    manager.discover_and_load_all()
    assert "Sobel Edge Detector" in _TOOL_REGISTRY


# --- 10. Workflow Persistence (Save / Load) with Plugin Tool ---

def test_plugin_tool_workflow_persistence():
    pipeline = VisionPipeline()
    tool_cls = get_tool_class("Sobel Edge Detector")
    tool = tool_cls(instance_id="sobel_save_test", name="Custom Edge Step")
    tool.set_param("direction", "Horizontal (X)")
    tool.set_param("ksize", 5)
    tool.set_param("scale", 2.5)
    pipeline.add_node(tool)

    # 1. Export & Import via Dict
    flow_data = pipeline.to_dict()
    loaded_pipeline = VisionPipeline.from_dict(flow_data)
    assert "sobel_save_test" in loaded_pipeline.nodes
    loaded_tool = loaded_pipeline.nodes["sobel_save_test"]

    assert loaded_tool.tool_name == "Sobel Edge Detector"
    assert loaded_tool.get_param("direction") == "Horizontal (X)"
    assert loaded_tool.get_param("ksize") == 5
    assert loaded_tool.get_param("scale") == 2.5

    # 2. Export & Import via XML
    xml_str = pipeline.to_xml()
    xml_pipeline = VisionPipeline.from_xml(xml_str)
    assert "sobel_save_test" in xml_pipeline.nodes
    xml_tool = xml_pipeline.nodes["sobel_save_test"]
    assert xml_tool.tool_name == "Sobel Edge Detector"
    assert xml_tool.get_param("direction") == "Horizontal (X)"
    assert xml_tool.get_param("ksize") == 5
    assert xml_tool.get_param("scale") == 2.5


# --- 11. Untrusted Execution Exception Containment ---

def test_plugin_exception_containment():
    tool_cls = get_tool_class("Sobel Edge Detector")
    tool = tool_cls(instance_id="sobel_fail_test")

    # Pass invalid non-image object under key "Image" to test error trapping
    corrupted_context = {"Image": "not_an_image"}
    res = tool.execute(corrupted_context)

    # Tool must return NG or ERROR, never raise an uncaught exception
    assert res.status in (ToolStatus.NG, ToolStatus.ERROR)
    assert res.message != ""


# --- 12. UI Integration Tests ---

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    from vm_clone.ui.styles import initialize_app_fonts
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_plugin_manager_dialog_ui(qapp):
    from vm_clone.ui.plugin_dialog import PluginManagerDialog

    dialog = PluginManagerDialog()
    dialog._suppress_msgbox = True
    assert dialog.table_plugins.rowCount() >= 1

    # Select the first row
    dialog.table_plugins.selectRow(0)
    dialog._on_selection_changed()
    assert len(dialog.txt_details.toPlainText()) > 0
    assert "Sobel Edge Detector" in dialog.txt_details.toPlainText()

    # Rescan
    dialog._on_rescan_clicked()
    assert dialog.table_plugins.rowCount() >= 1
    dialog.close()


def test_toolbox_panel_dynamic_category_ui(qapp):
    from PyQt6.QtCore import Qt
    from vm_clone.ui.toolbox import ToolBoxPanel

    toolbox = ToolBoxPanel()
    # Check that category rail includes Custom Filters from the loaded plugin
    categories = toolbox.rail.category_names()
    assert "Custom Filters" in categories

    # Select Custom Filters category
    toolbox.rail.select_category("Custom Filters")
    toolbox.flyout.show_category("Custom Filters")

    # The flyout grid should contain Sobel Edge Detector
    tool_names = [toolbox.flyout.grid.item(i).data(Qt.ItemDataRole.UserRole) for i in range(toolbox.flyout.grid.count())]
    assert "Sobel Edge Detector" in tool_names


def test_main_window_plugin_manager_action(qapp):
    from vm_clone.ui.main_window import VisionMasterMainWindow

    window = VisionMasterMainWindow()
    assert hasattr(window, "on_open_plugin_manager")

    # Find the Plugin Manager action in Tools menu
    menu_bar = window.menuBar()
    tools_menu = None
    for action in menu_bar.actions():
        if "Tools" in action.text():
            tools_menu = action.menu()
            break

    assert tools_menu is not None
    action_texts = [a.text() for a in tools_menu.actions()]
    assert any("Plugin Manager" in t for t in action_texts)
    window.close()

