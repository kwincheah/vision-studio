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
        mode = self.get_param("mode", "Simulation (Loopback Log)")
        fmt = self.get_param("format", "CSV")
        prefix = self.get_param("prefix", "VM_RES,")

        # Format message
        if fmt == "JSON" and isinstance(data, dict):
            payload_str = json.dumps(data)
        else:
            payload_str = f"{prefix}{str(data)}"

        raw_bytes = payload_str.encode('utf-8')
        sent_len = len(raw_bytes)

        if mode == "TCP Client":
            ip = self.get_param("server_ip", "127.0.0.1")
            port = int(self.get_param("server_port", 8080))
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    s.connect((ip, port))
                    s.sendall(raw_bytes)
            except Exception as e:
                # Still record attempt in simulation / non-blocking mode
                pass

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
        st = str(context.get("Status_In", "OK")).upper()
        is_ok = ("OK" in st or "PASS" in st or "TRUE" in st)

        line0 = True  # Strobe fires on each inspection
        line1 = is_ok
        line2 = not is_ok

        return ToolExecutionResult(
            status=ToolStatus.OK,
            message=f"Camera IO Out: Strobe=1, OK={int(line1)}, NG={int(line2)}",
            outputs={
                "Line0_Strobe": line0,
                "Line1_OK": line1,
                "Line2_NG": line2
            }
        )
