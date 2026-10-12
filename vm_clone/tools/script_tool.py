"""
Script and Custom Logic Tools.
Matches HikRobot Vision Master Global Script / Python Script Tool.
Allows industrial vision engineers to write custom Python/OpenCV logic inline.
"""
from typing import Dict, Any, List
import numpy as np
import cv2
from vm_clone.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from vm_clone.core.registry import register_tool


@register_tool
class ScriptTool(VisionToolBase):
    category = "Logic Tools"
    tool_name = "Script"
    description = "Executes custom Python script with access to context, OpenCV, NumPy, and outputs."

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.inputs["Val1"] = ToolPort("Val1", DataType.VALUE, "Numeric input 1")
        self.inputs["Val2"] = ToolPort("Val2", DataType.VALUE, "Numeric input 2")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through or modified image")
        self.outputs["Result"] = ToolPort("Result", DataType.ANY, "Script result")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "Script verdict")

    def _init_parameters(self):
        default_code = (
            "# inputs: context['Image'], context['Val1'], context['Val2']\n"
            "# assign to: outputs['Result'], outputs['Status'], overlays\n\n"
            "v1 = context.get('Val1', 0.0)\n"
            "v2 = context.get('Val2', 0.0)\n"
            "calc = v1 * 2.5 + v2\n"
            "outputs['Result'] = calc\n"
            "outputs['Status'] = 'OK' if calc > 0 else 'NG'\n"
            "overlays.append({'type': 'text', 'text': f'Script Calc: {calc:.2f}', 'pt': (20, 100), 'color': (255, 200, 0)})\n"
        )
        self.parameters = {
            "code": default_code
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        code = self.get_param("code", "")
        img = context.get("Image")

        outputs: Dict[str, Any] = {
            "Image": img,
            "Result": 0.0,
            "Status": "OK"
        }
        overlays: List[Dict[str, Any]] = []

        local_env = {
            "cv2": cv2,
            "np": np,
            "context": context,
            "outputs": outputs,
            "overlays": overlays
        }

        try:
            exec(code, {}, local_env)
            st = ToolStatus.OK if outputs.get("Status") == "OK" else ToolStatus.NG
            return ToolExecutionResult(
                status=st,
                message=f"Script executed. Result: {outputs.get('Result')}",
                outputs=outputs,
                overlays=overlays
            )
        except Exception as e:
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Script Error: {str(e)}",
                outputs=outputs,
                overlays=overlays
            )
