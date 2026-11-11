"""Communication Management in the real window: add a device, start it, a message arrives, a flow runs."""
import socket
import time

from PyQt6.QtCore import Qt

from test_qml_interaction import fresh, ui  # noqa: F401  (fixtures)
from apex_vision.core import comm_manager as cm
from apex_vision.core import dataqueue


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_backend_adds_starts_and_removes_a_device_and_keeps_it_in_the_solution(ui):
    be = ui.be
    cm.get_manager().load([])
    port = free_port()
    assert be.addCommDevice("plc", "TCP Server", "127.0.0.1", port, "\\n", "", False, "") == ""
    assert be.addCommDevice("plc", "TCP Server", "127.0.0.1", port, "\\n", "", False, "") != "", "no second device of that name"
    assert be._solution.comm_devices[0]["name"] == "plc"
    assert be.commDevices[0]["state"] == "Stopped"
    assert be.startCommDevice("plc") == ""
    assert be.commDevices[0]["state"] == "Running"
    c = socket.create_connection(("127.0.0.1", port), timeout=2)
    c.sendall(b"hello\n")
    end = time.time() + 3
    while time.time() < end and dataqueue.size(cm.queue_name("plc")) == 0:
        time.sleep(0.02)
    assert dataqueue.pop(cm.queue_name("plc")) == "hello"
    c.close()
    be.stopCommDevice("plc")
    assert be.commDevices[0]["state"] == "Stopped"
    ui.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    ui.spin(10)
    be.removeCommDevice("plc")
    assert be.commDevices == [] and be._solution.comm_devices == []
    cm.get_manager().load([])


def test_a_message_runs_the_devices_flow_and_leaves_the_text_in_a_global(ui):
    be = ui.be
    cm.get_manager().load([])
    port = free_port()
    flow = be._solution.active_flow_name
    assert be.addCommDevice("trig", "TCP Server", "127.0.0.1", port, "\\n", flow, False, "") == ""
    assert be.startCommDevice("trig") == ""
    before = be._pipeline.execution_count
    c = socket.create_connection(("127.0.0.1", port), timeout=2)
    c.sendall(b"GO-123\n")
    end = time.time() + 5
    while time.time() < end and be._solution.global_variables.get("g_LastMessage") != "GO-123":
        ui.spin(10)
    assert be._solution.global_variables.get("g_LastMessage") == "GO-123"
    end = time.time() + 5
    while time.time() < end and be._pipeline.execution_count == before:
        ui.spin(10)
    assert be._pipeline.execution_count > before, "the flow ran when the message arrived"
    c.close()
    cm.get_manager().load([])


def test_the_menu_item_opens_the_dialog_with_its_controls(ui):
    ui.main.invoke("comm")
    ui.spin(30)
    assert ui.dialog == "comm"
    names = {t.property("objectName") for t in ui.walk()}
    assert {"commTable", "commAdd", "commStart", "commStop", "commDelete", "commName"} <= names
    ui.close_dialog()
    assert ui.dialog == ""
