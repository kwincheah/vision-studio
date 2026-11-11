"""Communication Management: named network devices that belong to the whole solution (not to one module).

A device is a TCP server (a PLC or robot connects to us), a TCP client (we connect to it) or a UDP socket. Whatever arrives is split into
messages at the device's terminator and put on the queue ``device:<name>`` (see ``dataqueue``); the Receive Data module reads it from there,
and Send Data writes to the device. A device can also run a flow whenever a message arrives (the guide's global trigger).
"""
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from apex_vision.core import dataqueue

KINDS = ["TCP Server", "TCP Client", "UDP"]
QUEUE_PREFIX = "device:"


def _claim(sock: socket.socket) -> None:
    """Reserve the port: on Windows SO_REUSEADDR would let a second device bind the very same port, so ask for exclusive use there."""
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def queue_name(device: str) -> str:
    return QUEUE_PREFIX + device


def _unescape(text: str) -> str:
    return text.replace("\\r\\n", "\r\n").replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")


class CommDevice:
    def __init__(self, name: str, kind: str = "TCP Server", host: str = "0.0.0.0", port: int = 8000, terminator: str = "\\n", trigger_flow: str = "",
                 auto_start: bool = False, remote: str = ""):
        self.name = name
        self.kind = kind if kind in KINDS else "TCP Server"
        self.host = host
        self.port = int(port)
        self.terminator = terminator
        self.trigger_flow = trigger_flow         # run this flow whenever a message arrives ("" = none)
        self.auto_start = bool(auto_start)       # start it when the solution opens
        self.remote = remote                     # UDP: where Send Data goes, as host:port
        # runtime state, never saved
        self.running = False
        self.error = ""
        self.rx_count = 0
        self.tx_count = 0
        self.last_message = ""
        self.peers = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "host": self.host, "port": self.port, "terminator": self.terminator, "trigger_flow": self.trigger_flow,
                "auto_start": self.auto_start, "remote": self.remote}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CommDevice":
        return cls(str(d.get("name", "")), str(d.get("kind", "TCP Server")), str(d.get("host", "0.0.0.0")), int(d.get("port", 8000)), str(d.get("terminator", "\\n")),
                   str(d.get("trigger_flow", "")), bool(d.get("auto_start", False)), str(d.get("remote", "")))

    def status(self) -> Dict[str, Any]:
        endpoint = f"{self.host}:{self.port}"
        return {"name": self.name, "kind": self.kind, "endpoint": endpoint, "state": "Running" if self.running else ("Error" if self.error else "Stopped"),
                "error": self.error, "received": self.rx_count, "sent": self.tx_count, "last": self.last_message[:60], "peers": self.peers, "trigger": self.trigger_flow}


class _Runtime:
    """The sockets and threads of one running device."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.server: Optional[socket.socket] = None
        self.clients: List[socket.socket] = []
        self.lock = threading.Lock()
        self.threads: List[threading.Thread] = []
        self.last_udp_peer: Optional[tuple] = None


class CommManager:
    def __init__(self) -> None:
        self.devices: Dict[str, CommDevice] = {}
        self._rt: Dict[str, _Runtime] = {}
        self._lock = threading.Lock()
        self.on_message: Optional[Callable[[str, str], None]] = None

    # ---- the list of devices
    def load(self, items: List[Dict[str, Any]]) -> None:
        self.stop_all()
        self.devices = {}
        for d in items or []:
            try:
                dev = CommDevice.from_dict(d)
            except (TypeError, ValueError, AttributeError):
                continue
            if dev.name:
                self.devices[dev.name] = dev

    def dump(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self.devices.values()]

    def add(self, dev: CommDevice) -> Optional[str]:
        if not dev.name or not dev.name.replace("_", "").replace("-", "").isalnum():
            return "Name the device with letters, digits, - or _."
        if dev.name in self.devices:
            return f"There is already a device called '{dev.name}'."
        if not 1 <= dev.port <= 65535:
            return "The port must be between 1 and 65535."
        self.devices[dev.name] = dev
        return None

    def remove(self, name: str) -> None:
        self.stop(name)
        self.devices.pop(name, None)
        dataqueue.clear(queue_name(name))

    def status(self) -> List[Dict[str, Any]]:
        return [d.status() for d in self.devices.values()]

    # ---- running
    def start(self, name: str) -> Optional[str]:
        dev = self.devices.get(name)
        if dev is None:
            return f"There is no device called '{name}'."
        if dev.running:
            return None
        dev.error = ""
        rt = _Runtime()
        try:
            if dev.kind == "TCP Server":
                rt.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                _claim(rt.server)
                rt.server.bind((dev.host, dev.port))
                rt.server.listen(8)
                rt.server.settimeout(0.3)
                self._spawn(rt, self._accept_loop, dev, rt)
            elif dev.kind == "TCP Client":
                sock = socket.create_connection((dev.host, dev.port), timeout=3.0)
                sock.settimeout(0.3)
                rt.clients.append(sock)
                self._spawn(rt, self._read_loop, dev, rt, sock)
            else:
                rt.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                _claim(rt.server)
                rt.server.bind((dev.host, dev.port))
                rt.server.settimeout(0.3)
                self._spawn(rt, self._udp_loop, dev, rt)
        except OSError as e:
            dev.error = f"could not start: {e}"
            self._close(rt)
            return dev.error
        with self._lock:
            self._rt[name] = rt
        dev.running = True
        return None

    def stop(self, name: str) -> None:
        with self._lock:
            rt = self._rt.pop(name, None)
        if rt is not None:
            rt.stop.set()
            self._close(rt)
            for t in rt.threads:
                t.join(timeout=1.5)
        dev = self.devices.get(name)
        if dev is not None:
            dev.running = False
            dev.peers = 0

    def stop_all(self) -> None:
        for name in list(self._rt):
            self.stop(name)

    def start_auto(self) -> List[str]:
        """Start every device marked to start with the solution; returns the problems."""
        return [f"{d.name}: {e}" for d in self.devices.values() if d.auto_start and (e := self.start(d.name))]

    # ---- sending
    def send(self, name: str, text: str) -> Optional[str]:
        dev = self.devices.get(name)
        if dev is None:
            return f"There is no communication device called '{name}'."
        rt = self._rt.get(name)
        if not dev.running or rt is None:
            return f"The device '{name}' is not running: start it in Communication Management."
        term = _unescape(dev.terminator)
        data = (text if term and text.endswith(term) else text + term).encode("utf-8", "replace")
        try:
            if dev.kind == "UDP":
                target = None
                if dev.remote and ":" in dev.remote:
                    h, _, p = dev.remote.rpartition(":")
                    target = (h, int(p))
                elif rt.last_udp_peer:
                    target = rt.last_udp_peer
                if target is None:
                    return f"The UDP device '{name}' has nowhere to send: set its remote address, or wait for a message to reply to."
                rt.server.sendto(data, target)
            else:
                with rt.lock:
                    socks = list(rt.clients)
                if not socks:
                    return f"Nobody is connected to '{name}' yet."
                for s in socks:
                    s.sendall(data)
        except (OSError, ValueError) as e:
            return f"Could not send on '{name}': {e}"
        dev.tx_count += 1
        return None

    # ---- the threads
    def _spawn(self, rt: _Runtime, fn, *args) -> None:
        t = threading.Thread(target=fn, args=args, daemon=True, name="apex-comm")
        rt.threads.append(t)
        t.start()

    @staticmethod
    def _close(rt: _Runtime) -> None:
        for s in [rt.server] + list(rt.clients):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass

    def _deliver(self, dev: CommDevice, text: str) -> None:
        dev.rx_count += 1
        dev.last_message = text
        dataqueue.push(queue_name(dev.name), text)
        cb = self.on_message
        if cb is not None and dev.trigger_flow:
            try:
                cb(dev.name, text)
            except Exception:                    # noqa: BLE001 - a failing trigger must never kill the receive thread
                pass

    def _split(self, dev: CommDevice, buf: bytes):
        term = _unescape(dev.terminator).encode("utf-8")
        if not term:
            return ([buf] if buf else []), b""
        parts = buf.split(term)
        return [p for p in parts[:-1]], parts[-1]

    def _accept_loop(self, dev: CommDevice, rt: _Runtime) -> None:
        while not rt.stop.is_set():
            try:
                conn, _addr = rt.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(0.3)
            with rt.lock:
                rt.clients.append(conn)
                dev.peers = len(rt.clients)
            self._spawn(rt, self._read_loop, dev, rt, conn)

    def _read_loop(self, dev: CommDevice, rt: _Runtime, sock: socket.socket) -> None:
        buf = b""
        while not rt.stop.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            msgs, buf = self._split(dev, buf)
            for m in msgs:
                self._deliver(dev, m.decode("utf-8", "replace").rstrip("\r"))
            if not _unescape(dev.terminator) and buf:
                buf = b""
        with rt.lock:
            if sock in rt.clients:
                rt.clients.remove(sock)
            dev.peers = len(rt.clients)
        try:
            sock.close()
        except OSError:
            pass
        if dev.kind == "TCP Client" and not rt.stop.is_set():
            dev.running = False
            dev.error = "the connection was closed by the other side"

    def _udp_loop(self, dev: CommDevice, rt: _Runtime) -> None:
        while not rt.stop.is_set():
            try:
                data, addr = rt.server.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            rt.last_udp_peer = addr
            term = _unescape(dev.terminator)
            text = data.decode("utf-8", "replace")
            if term and text.endswith(term):
                text = text[:-len(term)]
            self._deliver(dev, text.rstrip("\r\n") if not term else text)


_MANAGER = CommManager()


def get_manager() -> CommManager:
    return _MANAGER
