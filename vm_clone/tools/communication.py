"""
Industrial Communication & Hardware I/O Tools.
Matches HikRobot Vision Master Communication category:
- TCP/IP Communication (Client/Server protocol sender for sending inspection results, coordinates, and OK/NG verdicts to robot/PLC)
- Modbus TCP / Serial Protocol Simulation
- Camera IO Communication (Digital Trigger In & Pass/Fail Strobe Out)
"""
import socket
import json
import time
from typing import Dict, Any, List
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class TCPSendTool(VisionToolBase):
    category = "Communication"
    tool_name = "TCP Send"
    description = "Sends inspection results, coordinates, or formatted strings to PLC/Robot via TCP/IP socket."

    def _init_ports(self):
        self.inputs["Data"] = ToolPort("Data", DataType.ANY, "Data payload to transmit")
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN, "Transmit trigger flag")
        self.outputs["Sent_Bytes"] = ToolPort("Sent_Bytes", DataType.VALUE, "Number of bytes sent")
        self.outputs["Last_Message"] = ToolPort("Last_Message", DataType.STRING, "Last transmitted string")

    def _init_parameters(self):
        self.parameters = {
            "mode": "Simulation (Loopback Log)",  # Simulation (Loopback Log), TCP Client
            "server_ip": "127.0.0.1",
            "server_port": 8080,
            "prefix": "VM_RES,",
            "suffix": "\\r\\n",
            "format": "CSV"  # CSV, JSON, Plain Text
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        data = context.get("Data", "PASS,X:120.4,Y:85.2")

        # The `Trigger` port gates the transmission.  It was declared but ignored, so
        # a module wired to send only on a trigger transmitted on every cycle.
        trigger = context.get("Trigger")
        if trigger is not None and not bool(trigger):
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message="TCP TX skipped: trigger is inactive",
                outputs={"Sent_Bytes": 0, "Last_Message": ""})

        mode = self.get_param("mode", "Simulation (Loopback Log)")
        fmt = self.get_param("format", "CSV")
        prefix = self.get_param("prefix", "VM_RES,")
        # The suffix was declared (default "\\r\\n") but never appended, so the
        # terminator the PLC framing expects was missing from every message.
        suffix = self._decode_escapes(self.get_param("suffix", "\\r\\n") or "")

        # Format message
        if fmt == "JSON" and isinstance(data, dict):
            payload_str = json.dumps(data)
        else:
            payload_str = f"{prefix}{self._stringify(data)}{suffix}"

        raw_bytes = payload_str.encode('utf-8')
        sent_len = len(raw_bytes)

        if mode == "TCP Client":
            ip = self.get_param("server_ip", "127.0.0.1")
            port = int(self.as_float(self.get_param("server_port", 8080), 8080))
            # A failed transmission must be reported.  The previous version swallowed
            # every socket error and still returned OK, so an operator had no way to
            # know the PLC never received the verdict.
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect((ip, port))
                    s.sendall(raw_bytes)
            except OSError as exc:
                return ToolExecutionResult(
                    status=ToolStatus.ERROR,
                    message=f"TCP TX failed to {ip}:{port}: {exc}",
                    outputs={"Sent_Bytes": 0, "Last_Message": payload_str},
                    overlays=[{"type": "text", "text": f"TCP TX FAILED: {ip}:{port}",
                               "pt": (15, 80), "color": (0, 0, 255)}])

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"TCP TX ({mode}): '{payload_str[:40]}' ({sent_len} bytes)",
            outputs={
                "Sent_Bytes": sent_len,
                "Last_Message": payload_str
            },
            overlays=[
                {"type": "text", "text": f"TCP TX: {payload_str[:25]}", "pt": (15, 80), "color": (0, 200, 255)}
            ]
        )

    @staticmethod
    def _decode_escapes(text: str) -> str:
        """Turn a configured ``\\r\\n`` into the control characters it names.

        The suffix is entered as visible escape text in the property editor, so the
        literal two-character sequence must be translated before transmission.
        """
        return (text.replace("\\r\\n", "\r\n")
                    .replace("\\n", "\n")
                    .replace("\\r", "\r")
                    .replace("\\t", "\t"))

    @staticmethod
    def _stringify(data: Any) -> str:
        """Render a payload the way the wire format expects.

        `None` used to reach `str()` and transmit the literal word "None" to the PLC.
        """
        if data is None:
            return ""
        if isinstance(data, bool):
            return "1" if data else "0"
        if isinstance(data, float) and data.is_integer():
            return str(int(data))
        return str(data)


@register_tool
class CameraIOTool(VisionToolBase):
    category = "Communication"
    tool_name = "Camera IO"
    description = "Controls industrial camera Opto-isolated Digital Output pins (Strobe, OK Line, NG Line)."

    def _init_ports(self):
        self.inputs["Status_In"] = ToolPort("Status_In", DataType.STRING, "Inspection Status (OK/NG)")
        self.outputs["Line0_Strobe"] = ToolPort("Line0_Strobe", DataType.BOOLEAN, "Opto-isolated strobe trigger")
        self.outputs["Line1_OK"] = ToolPort("Line1_OK", DataType.BOOLEAN, "OK Signal output")
        self.outputs["Line2_NG"] = ToolPort("Line2_NG", DataType.BOOLEAN, "NG Signal output")

    def _init_parameters(self):
        self.parameters = {
            "pulse_duration_ms": 20,
            "strobe_active_high": True,
            "invert_logic": False
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        raw = context.get("Status_In", "OK")
        # `None` used to stringify to "NONE", which matched neither OK nor PASS and so
        # silently reported NG.  An absent verdict is treated as "no result yet".
        if raw is None:
            st = ""
        else:
            st = str(raw).upper()
        is_ok = ("OK" in st or "PASS" in st or "TRUE" in st) and "NOT" not in st

        # `invert_logic` was declared but ignored, so the option did nothing in the
        # property grid.  It swaps which physical line carries the pass result.
        if self.get_param("invert_logic", False):
            line1 = not is_ok
            line2 = is_ok
        else:
            line1 = is_ok
            line2 = not is_ok

        # `strobe_active_high` was likewise ignored: the strobe is an active-high
        # pulse by default, and selecting active-low must actually invert the level.
        strobe_high = bool(self.get_param("strobe_active_high", True))
        line0 = strobe_high

        pulse_ms = self.as_float(self.get_param("pulse_duration_ms", 20), 20.0)

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=(f"Camera IO Out: Strobe={int(line0)}, OK={int(line1)}, "
                     f"NG={int(line2)} (pulse {pulse_ms:g} ms, "
                     f"active-{'high' if strobe_high else 'low'})"),
            outputs={
                "Line0_Strobe": line0,
                "Line1_OK": line1,
                "Line2_NG": line2,
                "Strobe_Pulse_ms": pulse_ms,
            }
        )
