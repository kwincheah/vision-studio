"""
More Communication modules: UDP Send, Serial Send, Modbus TCP Write and Data Log (CSV file).

Like TCP Send, the network and serial modules have a Simulation mode that only builds the message, so a flow can be
designed and tested with no PLC or robot connected. A failed real transmission is reported as an ERROR, never hidden.
"""
import csv
import json
import os
import socket
import struct
import time
from typing import Any, Dict, List

from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool

SIM = "Simulation (Log Only)"


def decode_escapes(text: str) -> str:
    return (text.replace("\\r\\n", "\r\n").replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t"))


def stringify(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, bool):
        return "1" if data else "0"
    if isinstance(data, float) and data.is_integer():
        return str(int(data))
    if isinstance(data, (list, tuple)):
        return ",".join(stringify(v) for v in data)
    if isinstance(data, dict):
        return ",".join(f"{k}:{stringify(v)}" for k, v in data.items())
    return str(data)


def build_message(tool: VisionToolBase, data: Any) -> str:
    fmt = tool.get_param("format", "CSV")
    prefix = str(tool.get_param("prefix", "") or "")
    suffix = decode_escapes(str(tool.get_param("suffix", "") or ""))
    if fmt == "JSON":
        try:
            return json.dumps(data, default=str) + suffix
        except (TypeError, ValueError):
            return json.dumps(str(data)) + suffix
    return f"{prefix}{stringify(data)}{suffix}"


def _gated(context: Dict[str, Any]) -> bool:
    trig = context.get("Trigger")
    return trig is not None and not bool(trig)


@register_tool
class UDPSendTool(VisionToolBase):
    category = "Communication"
    tool_name = "UDP Send"
    description = "Sends the inspection result as a UDP datagram to a PLC, robot or another computer."

    def _init_ports(self):
        self.inputs["Data"] = ToolPort("Data", DataType.ANY, "Data to transmit")
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN, "Only send while true")
        self.outputs["Sent_Bytes"] = ToolPort("Sent_Bytes", DataType.VALUE, "Bytes sent")
        self.outputs["Last_Message"] = ToolPort("Last_Message", DataType.STRING, "The message")

    def _init_parameters(self):
        self.parameters = {"mode": SIM, "server_ip": "127.0.0.1", "server_port": 9000,
                           "prefix": "APEX_RES,", "suffix": "\\r\\n", "format": "CSV"}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        if _gated(context):
            return ToolExecutionResult(status=ToolStatus.OK, message="UDP skipped: trigger is inactive",
                                       outputs={"Sent_Bytes": 0, "Last_Message": ""})
        text = build_message(self, context.get("Data", "PASS"))
        raw = text.encode("utf-8", "replace")
        mode = self.get_param("mode", SIM)
        if mode != SIM:
            ip = str(self.get_param("server_ip", "127.0.0.1"))
            port = int(self.as_float(self.get_param("server_port", 9000), 9000))
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.settimeout(1.0)
                    s.sendto(raw, (ip, port))
            except OSError as exc:
                return ToolExecutionResult(status=ToolStatus.ERROR, message=f"UDP TX failed to {ip}:{port}: {exc}",
                                           outputs={"Sent_Bytes": 0, "Last_Message": text})
        return ToolExecutionResult(status=ToolStatus.OK, message=f"UDP TX ({'simulated' if mode == SIM else 'sent'}): {len(raw)} bytes",
                                   outputs={"Sent_Bytes": len(raw), "Last_Message": text})


@register_tool
class SerialSendTool(VisionToolBase):
    category = "Communication"
    tool_name = "Serial Send"
    description = "Sends the inspection result out of a serial (COM / RS-232 / RS-485) port. Needs the 'pyserial' package for real ports."

    def _init_ports(self):
        self.inputs["Data"] = ToolPort("Data", DataType.ANY, "Data to transmit")
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN, "Only send while true")
        self.outputs["Sent_Bytes"] = ToolPort("Sent_Bytes", DataType.VALUE, "Bytes sent")
        self.outputs["Last_Message"] = ToolPort("Last_Message", DataType.STRING, "The message")

    def _init_parameters(self):
        self.parameters = {"mode": SIM, "port_name": "COM3", "baud_rate": "9600", "parity": "None",
                           "prefix": "APEX_RES,", "suffix": "\\r\\n", "format": "CSV"}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        if _gated(context):
            return ToolExecutionResult(status=ToolStatus.OK, message="Serial skipped: trigger is inactive",
                                       outputs={"Sent_Bytes": 0, "Last_Message": ""})
        text = build_message(self, context.get("Data", "PASS"))
        raw = text.encode("utf-8", "replace")
        mode = self.get_param("mode", SIM)
        if mode != SIM:
            port = str(self.get_param("port_name", "COM3"))
            try:
                import serial  # optional dependency
            except ImportError:
                return ToolExecutionResult(status=ToolStatus.ERROR,
                                           message="Serial ports need the 'pyserial' package: pip install pyserial",
                                           outputs={"Sent_Bytes": 0, "Last_Message": text})
            parity = {"None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN, "Odd": serial.PARITY_ODD}.get(
                str(self.get_param("parity", "None")), serial.PARITY_NONE)
            try:
                with serial.Serial(port, int(self.get_param("baud_rate", "9600")), parity=parity, timeout=1, write_timeout=1) as s:
                    s.write(raw)
            except (OSError, ValueError, serial.SerialException) as exc:
                return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Serial TX failed on {port}: {exc}",
                                           outputs={"Sent_Bytes": 0, "Last_Message": text})
        return ToolExecutionResult(status=ToolStatus.OK, message=f"Serial TX ({'simulated' if mode == SIM else 'sent'}): {len(raw)} bytes",
                                   outputs={"Sent_Bytes": len(raw), "Last_Message": text})


@register_tool
class ModbusWriteTool(VisionToolBase):
    category = "Communication"
    tool_name = "Modbus TCP Write"
    description = "Writes a result into a PLC register or coil over Modbus TCP (function 5, 6 or 16). Values are scaled to whole numbers."

    FUNCTIONS = ["Write Single Register", "Write Multiple Registers", "Write Single Coil"]

    def _init_ports(self):
        self.inputs["Data"] = ToolPort("Data", DataType.ANY, "A number, true/false, or a list of numbers")
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN, "Only write while true")
        self.outputs["Sent_Bytes"] = ToolPort("Sent_Bytes", DataType.VALUE, "Bytes sent")
        self.outputs["Last_Message"] = ToolPort("Last_Message", DataType.STRING, "What was written / the PLC reply")

    def _init_parameters(self):
        self.parameters = {"mode": SIM, "server_ip": "127.0.0.1", "server_port": 502, "unit_id": 1,
                           "function": "Write Single Register", "start_address": 0, "value_scale": 1.0,
                           "connect_timeout_ms": 1000}

    @staticmethod
    def _values(data: Any, scale: float) -> List[int]:
        items = data if isinstance(data, (list, tuple)) else [data]
        out = []
        for v in items[:120]:
            if isinstance(v, bool):
                out.append(int(v))
            else:
                try:
                    out.append(int(round(float(v) * scale)))
                except (TypeError, ValueError, OverflowError):
                    raise ValueError(f"'{v}' is not a number")
        if not out:
            raise ValueError("no value to write")
        return out

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        if _gated(context):
            return ToolExecutionResult(status=ToolStatus.OK, message="Modbus skipped: trigger is inactive",
                                       outputs={"Sent_Bytes": 0, "Last_Message": ""})
        try:
            vals = self._values(context.get("Data", 0), self.as_float(self.get_param("value_scale", 1.0), 1.0))
        except ValueError as exc:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Modbus: {exc}")
        func = self.get_param("function", "Write Single Register")
        addr = int(self.as_float(self.get_param("start_address", 0))) & 0xFFFF
        unit = int(self.as_float(self.get_param("unit_id", 1), 1)) & 0xFF
        try:
            if func == "Write Single Coil":
                pdu = struct.pack(">BHH", 5, addr, 0xFF00 if vals[0] else 0x0000)
            elif func == "Write Multiple Registers":
                regs = [v & 0xFFFF for v in vals]
                pdu = struct.pack(">BHHB", 16, addr, len(regs), 2 * len(regs)) + struct.pack(f">{len(regs)}H", *regs)
            else:
                pdu = struct.pack(">BHH", 6, addr, vals[0] & 0xFFFF)
        except struct.error as exc:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Modbus: value does not fit: {exc}")
        frame = struct.pack(">HHHB", int(time.time() * 1000) & 0xFFFF, 0, len(pdu) + 1, unit) + pdu
        desc = f"{func} @{addr} = {vals if len(vals) > 1 else vals[0]}"
        mode = self.get_param("mode", SIM)
        reply = ""
        if mode != SIM:
            ip = str(self.get_param("server_ip", "127.0.0.1"))
            port = int(self.as_float(self.get_param("server_port", 502), 502))
            try:
                with socket.create_connection((ip, port), timeout=max(0.05, self.as_float(self.get_param("connect_timeout_ms", 1000), 1000) / 1000.0)) as s:
                    s.sendall(frame)
                    data = s.recv(260)
                if len(data) >= 9 and data[7] & 0x80:
                    return ToolExecutionResult(status=ToolStatus.ERROR, message=f"PLC refused the write (exception code {data[8]})",
                                               outputs={"Sent_Bytes": len(frame), "Last_Message": desc})
                reply = data.hex()
            except OSError as exc:
                return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Modbus TX failed to {ip}:{port}: {exc}",
                                           outputs={"Sent_Bytes": 0, "Last_Message": desc})
        return ToolExecutionResult(status=ToolStatus.OK, message=f"Modbus ({'simulated' if mode == SIM else 'written'}): {desc}",
                                   outputs={"Sent_Bytes": len(frame), "Last_Message": desc + (f" reply {reply}" if reply else "")})


@register_tool
class DataLogTool(VisionToolBase):
    category = "Communication"
    tool_name = "Data Log"
    description = "Appends one row per run to a CSV file (time plus the values you connect), ready for Excel."

    def _init_ports(self):
        self.inputs["Data"] = ToolPort("Data", DataType.ANY, "A value, list of values, or name/value mapping")
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN, "Only log while true")
        self.outputs["Rows_Written"] = ToolPort("Rows_Written", DataType.VALUE, "Rows in this run (0 or 1)")
        self.outputs["File_Path"] = ToolPort("File_Path", DataType.STRING, "The CSV file")

    def _init_parameters(self):
        self.parameters = {"file_path": "./results/apex_log.csv", "add_timestamp": True}

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        path = str(self.get_param("file_path", "") or "").strip().strip('"')
        if _gated(context):
            return ToolExecutionResult(status=ToolStatus.OK, message="Log skipped: trigger is inactive",
                                       outputs={"Rows_Written": 0, "File_Path": path})
        if not path:
            return ToolExecutionResult(status=ToolStatus.ERROR, message="No log file chosen")
        if "Data" not in context:
            return ToolExecutionResult(status=ToolStatus.OK, message="Nothing to log: connect a value to 'Data'",
                                       outputs={"Rows_Written": 0, "File_Path": path})
        data = context.get("Data")
        if isinstance(data, dict):
            names, values = list(data.keys()), list(data.values())
        else:
            values = list(data) if isinstance(data, (list, tuple)) else [data]
            names = [f"value{i + 1}" for i in range(len(values))]
        row = [stringify(v) for v in values]
        head = [str(n) for n in names]
        if bool(self.get_param("add_timestamp", True)):
            row.insert(0, time.strftime("%Y-%m-%d %H:%M:%S"))
            head.insert(0, "time")
        try:
            folder = os.path.dirname(os.path.abspath(path))
            os.makedirs(folder, exist_ok=True)
            fresh = not os.path.exists(path) or os.path.getsize(path) == 0
            with open(path, "a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if fresh:
                    w.writerow(head)
                w.writerow(row)
        except OSError as exc:
            return ToolExecutionResult(status=ToolStatus.ERROR, message=f"Could not write the log: {exc}",
                                       outputs={"Rows_Written": 0, "File_Path": path})
        return ToolExecutionResult(status=ToolStatus.OK, message=f"Logged a row to {os.path.basename(path)}",
                                   outputs={"Rows_Written": 1, "File_Path": path})
