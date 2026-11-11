"""Communication Management: network devices that belong to the solution, with real sockets on this computer."""
import socket
import time

import pytest

import apex_vision.tools  # noqa: F401
from apex_vision.core import comm_manager as cm
from apex_vision.core import dataqueue
from apex_vision.core.base_tool import ToolStatus
from apex_vision.core.pipeline import SolutionManager
from apex_vision.core.registry import create_tool_instance


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_for(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def mgr():
    m = cm.CommManager()
    dataqueue.clear()
    yield m
    m.stop_all()
    dataqueue.clear()


def server(mgr, name="plc", **kw):
    dev = cm.CommDevice(name, "TCP Server", "127.0.0.1", free_port(), **kw)
    assert mgr.add(dev) is None
    assert mgr.start(name) is None
    return dev


def test_a_tcp_server_receives_messages_and_sends_back(mgr):
    dev = server(mgr)
    c = socket.create_connection(("127.0.0.1", dev.port), timeout=2)
    c.sendall(b"hello\nsecond\npart")
    assert wait_for(lambda: dev.rx_count == 2)
    assert dataqueue.pop(cm.queue_name("plc")) == "hello" and dataqueue.pop(cm.queue_name("plc")) == "second"
    c.sendall(b"ial\n")
    assert wait_for(lambda: dev.rx_count == 3) and dataqueue.pop(cm.queue_name("plc")) == "partial", "a message split across packets is put back together"
    assert dev.last_message == "partial" and dev.peers == 1 and mgr.status()[0]["state"] == "Running"
    assert mgr.send("plc", "OK;12") is None
    c.settimeout(2)
    assert c.recv(100) == b"OK;12\n"
    assert mgr.send("plc", "already\n") is None and c.recv(100) == b"already\n", "the terminator is not added twice"
    assert dev.tx_count == 2
    c.close()
    assert wait_for(lambda: dev.peers == 0)


def test_terminators_and_unframed_messages(mgr):
    dev = server(mgr, "a", terminator="\\r\\n")
    c = socket.create_connection(("127.0.0.1", dev.port), timeout=2)
    c.sendall(b"one\r\ntwo\r\n")
    assert wait_for(lambda: dev.rx_count == 2)
    assert [dataqueue.pop(cm.queue_name("a")), dataqueue.pop(cm.queue_name("a"))] == ["one", "two"]
    assert mgr.send("a", "reply") is None
    assert c.recv(100) == b"reply\r\n"
    raw = server(mgr, "raw", terminator="")
    c2 = socket.create_connection(("127.0.0.1", raw.port), timeout=2)
    c2.sendall(b"no end marker")
    assert wait_for(lambda: raw.rx_count == 1) and dataqueue.pop(cm.queue_name("raw")) == "no end marker"
    assert mgr.send("raw", "x") is None and c2.recv(10) == b"x"


def test_a_tcp_client_connects_out(mgr):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    dev = cm.CommDevice("robot", "TCP Client", "127.0.0.1", port)
    assert mgr.add(dev) is None and mgr.start("robot") is None
    conn, _ = srv.accept()
    conn.settimeout(2)
    conn.sendall(b"GO\n")
    assert wait_for(lambda: dev.rx_count == 1) and dataqueue.pop(cm.queue_name("robot")) == "GO"
    assert mgr.send("robot", "DONE") is None and conn.recv(20) == b"DONE\n"
    conn.close()
    assert wait_for(lambda: not dev.running) and "closed" in dev.error and mgr.status()[0]["state"] == "Error"
    srv.close()
    unreachable = cm.CommDevice("none", "TCP Client", "127.0.0.1", free_port())
    mgr.add(unreachable)
    assert "could not start" in mgr.start("none") and not unreachable.running and unreachable.error


def test_udp_devices(mgr):
    port = free_port(socket.SOCK_DGRAM)
    dev = cm.CommDevice("cam", "UDP", "127.0.0.1", port)
    assert mgr.add(dev) is None and mgr.start("cam") is None
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(("127.0.0.1", 0))
    peer.settimeout(2)
    assert "nowhere to send" in mgr.send("cam", "early")
    peer.sendto(b"ping\n", ("127.0.0.1", port))
    assert wait_for(lambda: dev.rx_count == 1) and dataqueue.pop(cm.queue_name("cam")) == "ping"
    assert mgr.send("cam", "pong") is None
    data, _ = peer.recvfrom(100)
    assert data == b"pong\n", "with no remote address it replies to the last sender"
    dev.remote = f"127.0.0.1:{peer.getsockname()[1]}"
    assert mgr.send("cam", "fixed") is None and peer.recvfrom(100)[0] == b"fixed\n"
    dev.remote = "127.0.0.1:notaport"
    assert "Could not send" in mgr.send("cam", "x")
    peer.close()


def test_a_message_can_trigger_a_flow(mgr):
    seen = []
    mgr.on_message = lambda name, text: seen.append((name, text))
    plain = server(mgr, "quiet")
    trig = server(mgr, "trig", trigger_flow="Flow1")
    for dev in (plain, trig):
        c = socket.create_connection(("127.0.0.1", dev.port), timeout=2)
        c.sendall(b"START\n")
        assert wait_for(lambda: dev.rx_count == 1)
        c.close()
    assert seen == [("trig", "START")], "only the device with a flow to run calls back"
    mgr.on_message = lambda *_: 1 / 0
    c = socket.create_connection(("127.0.0.1", trig.port), timeout=2)
    c.sendall(b"AGAIN\n")
    assert wait_for(lambda: trig.rx_count == 2), "a failing callback does not stop the device receiving"


def test_the_list_of_devices_and_its_rules(mgr):
    assert mgr.add(cm.CommDevice("", "TCP Server", port=80)) is not None
    assert mgr.add(cm.CommDevice("bad name!", "TCP Server", port=80)) is not None
    assert mgr.add(cm.CommDevice("p", "TCP Server", port=0)) is not None and mgr.add(cm.CommDevice("p", "TCP Server", port=70000)) is not None
    assert mgr.add(cm.CommDevice("ok_1", "TCP Server", "127.0.0.1", free_port())) is None
    assert "already" in mgr.add(cm.CommDevice("ok_1", "UDP", port=5000))
    assert mgr.start("ghost") and "no device" in mgr.start("ghost")
    assert "no communication device" in mgr.send("ghost", "x")
    assert "not running" in mgr.send("ok_1", "x")
    assert "Nobody is connected" in (mgr.start("ok_1") or mgr.send("ok_1", "x"))
    busy = cm.CommDevice("dup", "TCP Server", "127.0.0.1", mgr.devices["ok_1"].port)
    mgr.add(busy)
    assert "could not start" in mgr.start("dup") and mgr.status()[-1]["state"] == "Error"
    assert mgr.start("ok_1") is None, "starting a running device does nothing"
    mgr.stop("ok_1")
    assert not mgr.devices["ok_1"].running
    dataqueue.push(cm.queue_name("ok_1"), "left over")
    mgr.remove("ok_1")
    assert "ok_1" not in mgr.devices and dataqueue.size(cm.queue_name("ok_1")) == 0
    assert cm.CommDevice("x", "Bogus").kind == "TCP Server"


def test_devices_are_saved_with_the_solution_and_auto_start(mgr):
    port = free_port()
    sol = SolutionManager()
    sol.comm_devices = [cm.CommDevice("plc", "TCP Server", "127.0.0.1", port, trigger_flow="Flow1", auto_start=True).to_dict(), cm.CommDevice("u", "UDP", port=5005, remote="1.2.3.4:9").to_dict()]
    for again in (SolutionManager.from_dict(sol.to_dict()), SolutionManager.from_xml(sol.to_xml())):
        assert [d["name"] for d in again.comm_devices] == ["plc", "u"]
        assert again.comm_devices[0]["port"] == port and again.comm_devices[0]["auto_start"] is True and again.comm_devices[0]["trigger_flow"] == "Flow1"
        assert again.comm_devices[1]["remote"] == "1.2.3.4:9" and again.comm_devices[1]["auto_start"] is False
    assert "comm_devices" not in SolutionManager().to_dict(), "a solution without devices saves just what it did before"
    mgr.load(sol.comm_devices)
    assert sorted(mgr.devices) == ["plc", "u"] and not mgr.devices["plc"].running
    assert mgr.start_auto() == [] and mgr.devices["plc"].running and not mgr.devices["u"].running
    mgr.load([{"name": "z", "port": "bad"}, {"port": 5}, "junk"])
    assert list(mgr.devices) == [] and not any(d.running for d in mgr.devices.values()), "loading stops what was running"


def test_send_data_and_receive_data_use_the_devices():
    m = cm.get_manager()
    m.load([])
    dataqueue.clear()
    port = free_port()
    m.add(cm.CommDevice("line", "TCP Server", "127.0.0.1", port))
    try:
        assert m.start("line") is None
        c = socket.create_connection(("127.0.0.1", port), timeout=2)
        c.sendall(b"12;34\n")
        recv = create_tool_instance("Receive Data", "r")
        recv.set_param("source", "Communication Device")
        recv.set_param("name", "line")
        assert wait_for(lambda: dataqueue.size(cm.queue_name("line")) == 1)
        r = recv.execute({})
        assert r.status == ToolStatus.OK and r.outputs["Data"] == "12;34" and r.outputs["Has_Data"] == 1
        assert recv.execute({}).status == ToolStatus.NG, "the message was taken"
        send = create_tool_instance("Send Data", "s")
        send.set_param("target", "Communication Device")
        send.set_param("name", "line")
        assert send.execute({"Data": [1, 2, 3]}).status == ToolStatus.OK
        c.settimeout(2)
        assert c.recv(100) == b"1,2,3\n"
        missing = create_tool_instance("Send Data", "s2")
        missing.set_param("target", "Communication Device")
        missing.set_param("name", "ghost")
        bad = missing.execute({"Data": "x"})
        assert bad.status == ToolStatus.ERROR and "no communication device" in bad.message
        c.close()
    finally:
        m.load([])
        dataqueue.clear()
