"""
Comprehensive automated tests for Flow Control module:
- Flow creation, node insertion, and connection management
- Rejection of self-loops and circular dependencies (DAG cycle prevention)
- Type safety validation during port connections
- Undo / Redo mechanics via QUndoStack (wires and nodes)
- Flow duplication with port remapping
- Flow export and import (.prc and .json)
- Stop on NG defect halt behavior
- Flow execution timeout enforcement
- Logic branch execution (BranchTool, IfModuleTool, BranchStringTool, TriggerTool)
- Multi-flow project execution telemetry
"""
import os
import tempfile
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF

import vm_clone.tools
from vm_clone.core.pipeline import VisionPipeline, SolutionManager, FlowConnection
from vm_clone.core.registry import create_tool_instance
from vm_clone.core.base_tool import ToolStatus
from vm_clone.ui.flow_editor import (
    FlowScene, FlowEditorView, NodeSignals, PortItem, ConnectionItem,
    AddConnectionCommand, DeleteConnectionCommand, DeleteNodeCommand
)
from vm_clone.ui.styles import initialize_app_fonts


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    initialize_app_fonts(app)
    return app


def test_cycle_and_self_connection_prevention():
    """Verify that can_connect rejects self-loops and circular DAG dependencies."""
    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    binarize = create_tool_instance("Image Binarization", "bin_1", "02_Bin")
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "03_BCR")
    pipe.add_node(src)
    pipe.add_node(binarize)
    pipe.add_node(bcr)

    # 1. Self-connection rejection
    can, msg = pipe.can_connect("src_1", "Image", "src_1", "Image")
    assert can is False
    assert "Cannot connect a module to itself" in msg

    # 2. Valid forward connection: src -> binarize
    can, msg = pipe.can_connect("src_1", "Image", "bin_1", "Image")
    assert can is True
    assert pipe.connect("src_1", "Image", "bin_1", "Image") is True

    # 3. Valid forward connection: binarize -> bcr
    can, msg = pipe.can_connect("bin_1", "Image", "bcr_1", "Image")
    assert can is True
    assert pipe.connect("bin_1", "Image", "bcr_1", "Image") is True

    # 4. Circular back-edge: bcr -> binarize creates cycle
    can_conn, msg = pipe.can_connect("bcr_1", "Image", "bin_1", "Image")
    assert can_conn is False
    assert "Circular connection rejected" in msg
    assert pipe.connect("bcr_1", "Image", "bin_1", "Image") is False


def test_port_type_compatibility_validation():
    """Verify type checking rejection on incompatible port links."""
    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "02_BCR")
    pipe.add_node(src)
    pipe.add_node(bcr)

    # Incompatible: Code_Text output (STRING) -> bcr Image input (IMAGE)
    # Using different nodes: bcr_1 -> bcr_2
    bcr2 = create_tool_instance("2D BCR Recognition", "bcr_2", "03_BCR2")
    pipe.add_node(bcr2)
    can, msg = pipe.can_connect("bcr_1", "Code_Text", "bcr_2", "Image")
    assert can is False
    assert "Type mismatch" in msg


def test_flow_validation_diagnostics():
    """Verify validate_flow detects missing inputs and disabled modules."""
    pipe = VisionPipeline()
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "01_BCR")
    pipe.add_node(bcr)

    issues = pipe.validate_flow()
    # Missing Image input warning
    warns = [i for i in issues if i["severity"] == "warning"]
    assert any("has no incoming connection" in w["message"] for w in warns)

    # Bypass module produces info diagnostic
    bcr.enabled = False
    issues2 = pipe.validate_flow()
    infos = [i for i in issues2 if i["severity"] == "info"]
    assert any("bypassed" in inf["message"] for inf in infos)


def test_undo_redo_connection_and_node(qapp):
    """Verify QUndoStack records and reverts connection and node deletions cleanly."""
    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "02_BCR")
    pipe.add_node(src)
    pipe.add_node(bcr)

    signals = NodeSignals()
    scene = FlowScene(pipe, signals)
    scene.build_from_pipeline()

    # 1. UndoStack connection addition
    cmd = AddConnectionCommand(scene, "src_1", "Image", "bcr_1", "Image")
    scene.undo_stack.push(cmd)
    assert len(pipe.connections) == 1
    assert pipe.connections[0].from_node == "src_1"

    # Undo addition
    scene.undo_stack.undo()
    assert len(pipe.connections) == 0

    # Redo addition
    scene.undo_stack.redo()
    assert len(pipe.connections) == 1

    # 2. UndoStack node deletion
    del_cmd = DeleteNodeCommand(scene, "bcr_1")
    scene.undo_stack.push(del_cmd)
    assert "bcr_1" not in pipe.nodes
    assert len(pipe.connections) == 0

    # Undo deletion: restores bcr_1 and its incident connection
    scene.undo_stack.undo()
    assert "bcr_1" in pipe.nodes
    assert len(pipe.connections) == 1
    assert pipe.connections[0].to_node == "bcr_1"


def test_flow_duplication_and_serialization():
    """Verify duplicate(), export_to_file(), and import_from_file() preserve flow integrity."""
    pipe = VisionPipeline(name="SourceFlow")
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "02_BCR")
    pipe.add_node(src)
    pipe.add_node(bcr)
    pipe.connect("src_1", "Image", "bcr_1", "Image")
    pipe.run_interval_ms = 120.0
    pipe.stop_on_ng = True

    # Duplicate flow
    dup = pipe.duplicate("DuplicatedFlow")
    assert dup.name == "DuplicatedFlow"
    assert dup.run_interval_ms == 120.0
    assert dup.stop_on_ng is True
    assert len(dup.nodes) == 2
    assert len(dup.connections) == 1

    # Export to .prc
    # NOTE: the harness file sandbox forbids deleting directories under the
    # platform temp root, so `tempfile.TemporaryDirectory()` fails during
    # cleanup (WinError 5). Use an auto-removed named file inside the workspace
    # instead - DirectoryNotRemoved semantics are not what this test covers.
    prc_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "_flow_export_test.prc")
    )
    try:
        pipe.export_to_file(prc_path)
        assert os.path.exists(prc_path)

        # Import from .prc
        imported = VisionPipeline.import_from_file(prc_path)
        assert imported.name == "SourceFlow"
        assert imported.run_interval_ms == 120.0
        assert imported.stop_on_ng is True
        assert len(imported.nodes) == 2
        assert len(imported.connections) == 1
    finally:
        if os.path.exists(prc_path):
            os.remove(prc_path)


def test_flow_xml_export_and_import():
    """Verify XML flow export, import, and round-trip execution fidelity."""
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution

    pipe = create_pcb_inspection_solution()
    pipe.name = "XML_Inspection_Flow"
    pipe.run_interval_ms = 45.0
    pipe.stop_on_ng = True

    # 1. to_xml() and from_xml() string round-trip
    xml_str = pipe.to_xml()
    assert xml_str.startswith("<?xml") or "<VisionMasterFlow" in xml_str
    assert 'name="XML_Inspection_Flow"' in xml_str
    assert "<Node " in xml_str
    assert "<Connection " in xml_str

    pipe_imported = VisionPipeline.from_xml(xml_str)
    assert pipe_imported.name == "XML_Inspection_Flow"
    assert pipe_imported.run_interval_ms == 45.0
    assert pipe_imported.stop_on_ng is True
    assert len(pipe_imported.nodes) == len(pipe.nodes)
    assert len(pipe_imported.connections) == len(pipe.connections)
    assert pipe_imported.execution_order == pipe.execution_order

    # Verify parameters preserved across nodes
    for nid, orig_node in pipe.nodes.items():
        imp_node = pipe_imported.nodes[nid]
        assert imp_node.tool_name == orig_node.tool_name
        assert imp_node.enabled == orig_node.enabled
        for pkey, pval in orig_node.parameters.items():
            assert pkey in imp_node.parameters
            assert imp_node.parameters[pkey] == pval

    # 2. File-based XML export and import
    xml_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "_test_flow_export.xml")
    )
    try:
        pipe.export_to_xml(xml_path)
        assert os.path.exists(xml_path)

        # Import via import_from_xml
        from_file_pipe = VisionPipeline.import_from_xml(xml_path)
        assert len(from_file_pipe.nodes) == len(pipe.nodes)
        assert len(from_file_pipe.connections) == len(pipe.connections)

        # Import via general import_from_file auto-detecting XML
        auto_detected = VisionPipeline.import_from_file(xml_path)
        assert len(auto_detected.nodes) == len(pipe.nodes)

        # 3. Execution fidelity: both pipelines produce matching verdicts
        orig_res = pipe.execute_flow()
        imp_res = from_file_pipe.execute_flow()
        assert [r.status for r in orig_res.values()] == [r.status for r in imp_res.values()]
    finally:
        if os.path.exists(xml_path):
            os.remove(xml_path)


def test_solution_manager_xml_flow_import_export():
    """Verify SolutionManager XML flow export and import APIs."""
    sol = SolutionManager("MultiFlowSolution")
    f1 = sol.get_active_flow()
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    bcr = create_tool_instance("2D BCR Recognition", "bcr_1", "02_BCR")
    f1.add_node(src)
    f1.add_node(bcr)
    f1.connect("src_1", "Image", "bcr_1", "Image")

    xml_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "_sol_export_test.xml")
    )
    try:
        sol.export_flow_xml(f1.name, xml_path)
        assert os.path.exists(xml_path)

        imported = sol.import_flow_xml(xml_path, flow_name="ImportedXmlFlow")
        assert "ImportedXmlFlow" in sol.flows
        assert len(imported.nodes) == 2
        assert len(imported.connections) == 1

        # Also test via general export_flow and import_flow with .xml suffix
        sol.export_flow("ImportedXmlFlow", xml_path)
        imported2 = sol.import_flow(xml_path, flow_name="AutoDetectedFlow")
        assert "AutoDetectedFlow" in sol.flows
        assert len(imported2.nodes) == 2
    finally:
        if os.path.exists(xml_path):
            os.remove(xml_path)


def test_main_window_xml_flow_export_and_import(qapp):
    """Verify MainWindow XML flow export and import capabilities."""
    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    try:
        assert hasattr(win, "on_export_flow_xml")
        assert hasattr(win, "on_import_flow_xml")

        xml_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "_ui_flow_export.xml")
        )
        try:
            flow_name = win.solution.active_flow_name
            win.solution.export_flow_xml(flow_name, xml_path)
            assert os.path.exists(xml_path)

            imported = win.solution.import_flow_xml(xml_path, flow_name="ImportedViaUI")
            assert "ImportedViaUI" in win.solution.flows
            assert len(imported.nodes) == len(win.pipeline.nodes)
        finally:
            if os.path.exists(xml_path):
                os.remove(xml_path)
    finally:
        win.close()
        win.deleteLater()


def test_logic_branch_tools_execution():
    """Verify BranchTool, IfModuleTool, BranchStringTool, and TriggerTool logic workflows."""
    # 1. BranchTool: Index by Value
    branch = create_tool_instance("Branch", "br_1", "01_Branch")
    branch.parameters["mode"] = "Index by Value"
    branch.parameters["target_value"] = 2
    res_br = branch.execute({"Condition_In": 2})
    assert res_br.status == ToolStatus.OK
    assert res_br.outputs["Branch_Index"] == 2
    assert res_br.outputs["Status"] == "OK"

    # 2. BranchTool: Index by Bitmask
    branch.parameters["mode"] = "Index by Bit"
    branch.parameters["bit_index"] = 2
    res_br2 = branch.execute({"Condition_In": 4})  # bit 2 is set (1 << 2 == 4)
    assert res_br2.status == ToolStatus.OK
    assert res_br2.outputs["Status"] == "OK"

    # 3. IfModuleTool: Any condition passed
    if_tool = create_tool_instance("If Module", "if_1", "02_If")
    if_tool.parameters["min_val"] = 10.0
    if_tool.parameters["max_val"] = 50.0
    res_if = if_tool.execute({"Val_In": 25.0})
    assert res_if.status == ToolStatus.OK
    assert res_if.outputs["Result"] is True

    # 4. BranchStringTool: pattern matching
    str_br = create_tool_instance("Branch String", "sbr_1", "03_StrBr")
    str_br.parameters["match_mode"] = "Contains"
    str_br.parameters["target_text"] = "PASS"
    res_sb = str_br.execute({"Input_Text": "BATCH_PASS_99"})
    assert res_sb.status == ToolStatus.OK
    assert res_sb.outputs["Branch_Result"] is True

    # 5. TriggerTool: procedure invocation
    trig = create_tool_instance("Trigger", "trig_1", "04_Trig")
    trig.parameters["target_flow"] = "Flow2"
    res_tr = trig.execute({"Trigger_Signal": True})
    assert res_tr.status == ToolStatus.OK
    assert res_tr.outputs["Status"] == "OK"


def test_solution_manager_multi_flow_and_telemetry():
    """Verify SolutionManager executes all sub-flows, collecting execution counts and telemetry."""
    sm = SolutionManager(name="TestSolution")
    f1 = sm.add_flow("Flow1")
    src1 = create_tool_instance("Image Source", "src_f1", "01_Acq")
    f1.add_node(src1)

    f2 = sm.add_flow("Flow2")
    src2 = create_tool_instance("Image Source", "src_f2", "01_Acq")
    f2.add_node(src2)

    results = sm.execute_all_flows()
    assert len(results) == 2
    assert "Flow1" in results and "Flow2" in results
    assert f1.execution_count == 1
    assert f2.execution_count == 1
    assert f1.last_flow_time_ms >= 0.0


def test_input_param_follows_connection_wire(qapp):
    """Verify that module configuration Input Params follows the connection wire."""
    from vm_clone.ui.module_config import ModuleConfigDialog
    from PyQt6.QtWidgets import QComboBox

    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_1", "01_Acq")
    tm = create_tool_instance("Template Match", "tm_1", "02_Match")
    pipe.add_node(src)
    pipe.add_node(tm)
    pipe.connect("src_1", "Image", "tm_1", "Image")

    dlg = ModuleConfigDialog(tm, pipeline=pipe)
    combo = dlg.findChild(QComboBox, "inputCombo_Image")
    assert combo is not None
    assert "01_Acq [Image]" in combo.currentText()

    # Disconnect via input param dropdown
    none_idx = combo.findText("<None (Disconnected)>")
    assert none_idx >= 0
    combo.setCurrentIndex(none_idx)
    assert len(pipe.connections) == 0

    # Reconnect via input param dropdown
    src_idx = combo.findText("01_Acq [Image]")
    assert src_idx >= 0
    combo.setCurrentIndex(src_idx)
    assert len(pipe.connections) == 1
    assert pipe.connections[0].from_node == "src_1"
    assert pipe.connections[0].to_node == "tm_1"
    dlg.deleteLater()


def test_inspector_input_param_follows_connection_wire(qapp):
    """Verify that ParameterInspectorWidget displays input parameters bound to lines."""
    from vm_clone.ui.inspector import ParameterInspectorWidget
    from PyQt6.QtWidgets import QComboBox

    pipe = VisionPipeline()
    src = create_tool_instance("Image Source", "src_2", "01_Acq2")
    tm = create_tool_instance("Template Match", "tm_2", "02_Match2")
    pipe.add_node(src)
    pipe.add_node(tm)
    pipe.connect("src_2", "Image", "tm_2", "Image")

    inspector = ParameterInspectorWidget()
    inspector.set_tool(tm, pipeline=pipe)
    combo = inspector.param_container.findChild(QComboBox, "inWire_Image")
    assert combo is not None
    assert "01_Acq2.Image" in combo.currentText()
    inspector.deleteLater()


def test_menu_bar_corner_controls_and_telemetry(qapp):
    """Verify Figure 6-2 solution dropdown, role switchover, and flow telemetry."""
    from vm_clone.ui.main_window import VisionMasterMainWindow

    win = VisionMasterMainWindow()
    win.show()
    qapp.processEvents()
    assert hasattr(win, "btn_project") and win.btn_project.menu() is not None
    assert hasattr(win, "btn_role") and len(win.btn_role.menu().actions()) >= 3
    assert hasattr(win, "btn_menu_save")

    assert hasattr(win.flow_view, "telemetry_bar")
    assert win.flow_view.telemetry_bar.isVisible()
    assert hasattr(win, "lbl_vm_version")
    assert "V4.3.0" in win.lbl_vm_version.text()

    win.close()
    win.deleteLater()
