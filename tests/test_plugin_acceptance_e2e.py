"""End-to-End Acceptance Test Suite for Vision Master Modular Plugin System.

Validates:
1. Full Application Launch & Plugin Auto-Discovery (sample Sobel Edge plugin)
2. Interactive Canvas Insertion, Port Wiring, Schema-Driven Configuration & DAG Execution
3. Project Persistence (Save to .vmp and Restore from Disk) with Plugin Nodes
4. Hot Unloading with Strict Stale UI and Stale Registry Checks
5. Negative Testing: Syntax Errors, Missing Dependencies, Incompatible SemVer, Malformed Manifests
6. Repeated Load/Unload Cycles (Stress and Idempotence)
7. Execution Failures, Fault Containment & Sandboxing Behavior
8. Workflow Loading with Missing / Uninstalled Plugins (Graceful Placeholder Degradation)
"""
import os
import json
import tempfile
import pytest
import numpy as np

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF

import apex_vision.tools
from apex_vision.sdk import (
    CURRENT_SDK_VERSION,
    PluginMetadata,
    PluginToolBase,
    IVisionPlugin,
    ParamDef,
    ParamType,
    DataType,
    ToolPort,
    ToolExecutionResult,
    ToolStatus,
)
from apex_vision.sdk.manager import PluginManager, PluginState
from apex_vision.core.registry import _TOOL_REGISTRY, _CATEGORIES, get_tool_class, create_tool_instance
from apex_vision.core.base_tool import MissingPluginPlaceholderTool
from apex_vision.core.pipeline import VisionPipeline, SolutionManager
from apex_vision.core.project_manager import ProjectManager
from apex_vision.ui.main_window import VisionMasterMainWindow
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
# 1. Full Application Launch & Auto-Discovery
# =============================================================================

def test_app_launch_and_plugin_discovery(qapp):
    win = VisionMasterMainWindow()
    pm = PluginManager.get_instance()

    # Verify plugin auto-discovered on app startup
    plugins = pm.list_plugins()
    plugin_ids = [p.metadata.plugin_id for p in plugins]
    assert "sample_sobel_edge_plugin" in plugin_ids

    sobel_rec = pm.get_plugin("sample_sobel_edge_plugin")
    assert sobel_rec is not None
    assert sobel_rec.state == PluginState.LOADED
    assert sobel_rec.metadata.name == "Sobel Edge Detector"

    # Verify tool in registry and category rail
    assert "Sobel Edge Detector" in _TOOL_REGISTRY
    assert "Custom Filters" in _CATEGORIES
    assert "Sobel Edge Detector" in _CATEGORIES["Custom Filters"]

    # Verify UI toolbox has the category and tool
    rail_cats = win.toolbox.rail.category_names()
    assert "Custom Filters" in rail_cats

    win.toolbox.rail.select_category("Custom Filters")
    win.toolbox.flyout.show_category("Custom Filters")
    flyout_tools = [
        win.toolbox.flyout.grid.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(win.toolbox.flyout.grid.count())
    ]
    assert "Sobel Edge Detector" in flyout_tools

    win.close()


# =============================================================================
# 2. Canvas Insertion, Wiring, Configuration & Execution
# =============================================================================

def test_e2e_canvas_workflow_execution(qapp):
    win = VisionMasterMainWindow()
    pipeline = win.pipeline

    # 1. Insert Image Source and Sobel Edge Detector
    win.on_add_tool_by_name("Image Source")
    win.on_add_tool_by_name("Sobel Edge Detector")

    # Find the inserted nodes
    src_node_id = next((nid for nid, tool in pipeline.nodes.items() if tool.tool_name == "Image Source"), None)
    sobel_node_id = next((nid for nid, tool in pipeline.nodes.items() if tool.tool_name == "Sobel Edge Detector"), None)

    assert src_node_id is not None
    assert sobel_node_id is not None

    src_tool = pipeline.nodes[src_node_id]
    sobel_tool = pipeline.nodes[sobel_node_id]

    # 2. Wire Image Source -> Sobel Edge Detector
    connected = pipeline.connect(src_node_id, "Image", sobel_node_id, "Image")
    assert connected is True

    # 3. Test Schema-Driven ParameterInspectorWidget Configuration
    from apex_vision.ui.inspector import ParameterInspectorWidget
    inspector = ParameterInspectorWidget()
    inspector.set_tool(sobel_tool)
    assert inspector.current_tool == sobel_tool

    # Verify parameter layout built
    form_layout = inspector.param_layout
    assert form_layout.rowCount() > 0

    # Modify parameters via inspector API and check tool values
    inspector._on_val_changed("direction", "Horizontal (X)")
    inspector._on_val_changed("ksize", 5)
    inspector._on_val_changed("scale", 2.0)
    inspector._on_val_changed("invert", True)

    assert sobel_tool.get_param("direction") == "Horizontal (X)"
    assert sobel_tool.get_param("ksize") == 5
    assert sobel_tool.get_param("scale") == 2.0
    assert sobel_tool.get_param("invert") is True

    # 4. Execute Flow through Main Window execution action
    win.on_run_once()

    # Check results in pipeline
    last_results = pipeline.last_results
    assert sobel_node_id in last_results
    sobel_res = last_results[sobel_node_id]

    assert sobel_res.status == ToolStatus.OK
    assert "Image" in sobel_res.outputs
    assert "Edge_Intensity" in sobel_res.outputs
    assert isinstance(sobel_res.outputs["Image"], np.ndarray)
    assert sobel_res.outputs["Edge_Intensity"] >= 0.0

    # Verify ParameterInspectorWidget verdict strip shows OK
    inspector.update_results(sobel_res)
    assert "OK" in inspector.lbl_verdict.text().upper()

    win.close()


# =============================================================================
# 3. Project Persistence (Save and Restore from Disk)
# =============================================================================

def test_e2e_project_save_and_restore_with_plugin(qapp, tmp_path):
    proj_mgr = ProjectManager(workspace_root=str(tmp_path))

    # Create solution with Sobel plugin node
    sol = SolutionManager(name="PluginAcceptanceTest")
    pipe = VisionPipeline(name="Flow1")

    src = create_tool_instance("Image Source", "node_src", "01_Acquisition")
    sobel = create_tool_instance("Sobel Edge Detector", "node_sobel", "02_SobelFilter")
    sobel.set_param("direction", "Vertical (Y)")
    sobel.set_param("ksize", 5)
    sobel.set_param("scale", 1.8)

    pipe.add_node(src)
    pipe.add_node(sobel)
    pipe.connect("node_src", "Image", "node_sobel", "Image")

    sol.flows["Flow1"] = pipe
    sol.active_flow_name = "Flow1"

    # Save to .vmp project file
    project_file = str(tmp_path / "PluginSolution.vmp")
    sol.save_to_file(project_file)
    assert os.path.exists(project_file)

    # Restore project from disk
    restored_sol = SolutionManager.load_from_file(project_file)
    assert "Flow1" in restored_sol.flows
    restored_pipe = restored_sol.flows["Flow1"]

    assert "node_sobel" in restored_pipe.nodes
    restored_sobel = restored_pipe.nodes["node_sobel"]
    assert restored_sobel.tool_name == "Sobel Edge Detector"
    assert restored_sobel.get_param("direction") == "Vertical (Y)"
    assert restored_sobel.get_param("ksize") == 5
    assert restored_sobel.get_param("scale") == 1.8

    # Verify execution of restored pipeline
    exec_res = restored_pipe.execute_flow()
    assert "node_sobel" in exec_res
    assert exec_res["node_sobel"].status == ToolStatus.OK
    assert exec_res["node_sobel"].outputs["Edge_Intensity"] >= 0.0


# =============================================================================
# 4. Hot Unloading with Strict Stale UI & Registry Checks
# =============================================================================

def test_e2e_unload_without_stale_ui_or_registry(qapp):
    win = VisionMasterMainWindow()
    pm = PluginManager.get_instance()

    # Ensure plugin is loaded first
    pm.discover_and_load_all()
    win.toolbox.refresh_tools()
    assert "Custom Filters" in win.toolbox.rail.category_names()
    assert "Sobel Edge Detector" in _TOOL_REGISTRY

    # Open Plugin Manager Dialog and trigger Unload
    dlg = PluginManagerDialog(win)
    dlg._suppress_msgbox = True

    # Find row for sample_sobel_edge_plugin
    target_row = -1
    for r in range(dlg.table_plugins.rowCount()):
        pid = dlg.table_plugins.item(r, 0).data(Qt.ItemDataRole.UserRole)
        if pid == "sample_sobel_edge_plugin":
            target_row = r
            break
    assert target_row >= 0

    dlg.table_plugins.selectRow(target_row)
    dlg._on_unload_clicked()
    dlg.close()

    # 1. Check Registry State
    assert "Sobel Edge Detector" not in _TOOL_REGISTRY
    assert "Custom Filters" not in _CATEGORIES

    # 2. Check UI Toolbox - No stale category button on the rail!
    win.toolbox.refresh_tools()
    assert "Custom Filters" not in win.toolbox.rail.category_names()

    # 3. Check UI Toolbox - No stale tool in flyout!
    for cat_name in win.toolbox.rail.category_names():
        win.toolbox.flyout.show_category(cat_name)
        tool_names = [
            win.toolbox.flyout.grid.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(win.toolbox.flyout.grid.count())
        ]
        assert "Sobel Edge Detector" not in tool_names

    # 4. Restore plugin for subsequent tests
    pm.discover_and_load_all()
    win.toolbox.refresh_tools()
    assert "Sobel Edge Detector" in _TOOL_REGISTRY
    win.close()


# =============================================================================
# 5. Negative Testing: Syntax Errors, Missing Dependencies, Incompatible Versions
# =============================================================================

def test_negative_syntax_error_plugin(tmp_path):
    bad_dir = tmp_path / "syntax_error_plugin"
    bad_dir.mkdir()
    (bad_dir / "plugin.json").write_text(json.dumps({
        "id": "syntax_error_plugin",
        "name": "Syntax Error Plugin",
        "version": "1.0.0",
        "min_sdk_version": "1.0.0",
        "entrypoint": "__init__.py"
    }), encoding="utf-8")
    (bad_dir / "__init__.py").write_text("def broken_syntax(:\n    pass\n", encoding="utf-8")

    pm = PluginManager(plugin_dirs=[str(tmp_path)])
    rec = pm.load_plugin_from_directory(str(bad_dir))

    assert rec is not None
    assert rec.state == PluginState.ERROR
    assert "invalid syntax" in rec.error_message or "SyntaxError" in rec.error_message


def test_negative_missing_dependency_plugin(tmp_path):
    missing_dir = tmp_path / "missing_dep_plugin"
    missing_dir.mkdir()
    (missing_dir / "plugin.json").write_text(json.dumps({
        "id": "missing_dep_plugin",
        "name": "Missing Dependency Plugin",
        "version": "1.0.0",
        "min_sdk_version": "1.0.0",
        "entrypoint": "__init__.py"
    }), encoding="utf-8")
    (missing_dir / "__init__.py").write_text(
        "import definitely_non_existent_vision_package_xyz\n",
        encoding="utf-8"
    )

    pm = PluginManager(plugin_dirs=[str(tmp_path)])
    rec = pm.load_plugin_from_directory(str(missing_dir))

    assert rec is not None
    assert rec.state == PluginState.ERROR
    assert "definitely_non_existent_vision_package_xyz" in rec.error_message


def test_negative_incompatible_sdk_version_plugin(tmp_path):
    incompat_dir = tmp_path / "future_sdk_plugin"
    incompat_dir.mkdir()
    (incompat_dir / "plugin.json").write_text(json.dumps({
        "id": "future_sdk_plugin",
        "name": "Future SDK Plugin",
        "version": "1.0.0",
        "min_sdk_version": "9.0.0",
        "entrypoint": "__init__.py"
    }), encoding="utf-8")
    (incompat_dir / "__init__.py").write_text("# ok\n", encoding="utf-8")

    pm = PluginManager(plugin_dirs=[str(tmp_path)])
    rec = pm.load_plugin_from_directory(str(incompat_dir))

    assert rec is not None
    assert rec.state == PluginState.INCOMPATIBLE
    assert "SDK version mismatch" in rec.error_message


# =============================================================================
# 6. Repeated Load/Unload Cycles (Stress & Idempotence)
# =============================================================================

def test_repeated_load_unload_cycles():
    pm = PluginManager.get_instance()
    plugin_id = "sample_sobel_edge_plugin"
    plugin_dir = os.path.abspath(os.path.join("plugins", plugin_id))

    for cycle in range(5):
        # 1. Load / Reload
        rec = pm.load_plugin_from_directory(plugin_dir, reload=True)
        assert rec is not None
        assert rec.state == PluginState.LOADED
        assert "Sobel Edge Detector" in _TOOL_REGISTRY
        assert "Custom Filters" in _CATEGORIES

        # Verify no duplicate entries in category list
        cat_tools = _CATEGORIES["Custom Filters"]
        assert cat_tools.count("Sobel Edge Detector") == 1

        # 2. Unload
        unloaded = pm.unload_plugin(plugin_id)
        assert unloaded is True
        assert "Sobel Edge Detector" not in _TOOL_REGISTRY
        assert "Custom Filters" not in _CATEGORIES

    # Re-enable plugin for remainder
    pm.discover_and_load_all()
    assert "Sobel Edge Detector" in _TOOL_REGISTRY


# =============================================================================
# 7. Execution Failures, Fault Containment & Sandboxing Behavior
# =============================================================================

class IntentionalFailureTool(PluginToolBase):
    tool_name = "Intentional Failure Tool"
    category = "Diagnostics"

    def execute(self, context):
        # Deliberately raise unhandled runtime error
        raise ZeroDivisionError("Intentional test division by zero in plugin tool")


def test_plugin_execution_failures_containment():
    pipeline = VisionPipeline(name="FailureTestFlow")
    fail_tool = IntentionalFailureTool(instance_id="fail_node_1")
    pipeline.add_node(fail_tool)

    # Executing the flow MUST trap the exception and return ToolStatus.ERROR
    results = pipeline.execute_flow()
    assert "fail_node_1" in results
    res = results["fail_node_1"]

    assert res.status == ToolStatus.ERROR
    assert "ZeroDivisionError" in res.message or "Intentional test division by zero" in res.message


# =============================================================================
# 8. Workflow Loading with Missing / Uninstalled Plugins (Graceful Placeholder)
# =============================================================================

def test_workflow_load_missing_plugin_placeholder():
    # Construct workflow data referencing a tool that does not exist in registry
    flow_data = {
        "name": "MissingPluginFlow",
        "nodes": [
            {
                "instance_id": "ghost_node_1",
                "tool_name": "NonExistentThirdPartyPluginTool",
                "name": "Ghost Step",
                "parameters": {"sens_threshold": 99}
            }
        ],
        "connections": []
    }

    # Deserializing MUST NOT crash with KeyError: it must build a MissingPluginPlaceholderTool
    pipeline = VisionPipeline.from_dict(flow_data)
    assert "ghost_node_1" in pipeline.nodes
    placeholder_tool = pipeline.nodes["ghost_node_1"]

    assert isinstance(placeholder_tool, MissingPluginPlaceholderTool)
    assert placeholder_tool.missing_tool_name == "NonExistentThirdPartyPluginTool"

    # Executing the pipeline flags the missing node as ERROR gracefully
    results = pipeline.execute_flow()
    assert "ghost_node_1" in results
    assert results["ghost_node_1"].status == ToolStatus.ERROR
    assert "not installed or failed to load" in results["ghost_node_1"].message

    # Re-exporting preserves the original tool_name
    exported_data = pipeline.to_dict()
    assert exported_data["nodes"][0]["tool_name"] == "NonExistentThirdPartyPluginTool"
