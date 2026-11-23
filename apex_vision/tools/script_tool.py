"""
Script and Custom Logic Tools.
Matches the reference product Global Script / Python Script Tool.
Allows industrial vision engineers to write custom Python/OpenCV logic inline.
"""
import base64
from collections import deque
import ctypes
import json
import math
import re
import threading
import time
import traceback
from typing import Dict, Any, List
import numpy as np
import cv2
from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool

_SCRIPT_PORT_TYPES: Dict[str, DataType] = {
    "ANY": DataType.ANY,
    "IMAGE": DataType.IMAGE,
    "STRING": DataType.STRING,
    "VALUE": DataType.VALUE,
    "BOOLEAN": DataType.BOOLEAN,
    "REGION": DataType.REGION,
}

_PORT_DEFAULTS: Dict[str, Any] = {
    "ANY": None,
    "IMAGE": None,
    "STRING": "",
    "VALUE": 0.0,
    "BOOLEAN": False,
    "REGION": [0, 0, 0, 0],
}


class ScriptTimeout(BaseException):
    """Raised inside a script that ran past its time limit.

    Not an Exception subclass, so a script's own ``except Exception`` cannot swallow it."""


def run_with_deadline(code_obj, env: Dict[str, Any], timeout_s: float) -> None:
    """Run ``code_obj`` in ``env``; if it is still running after ``timeout_s`` seconds, raise ScriptTimeout inside it.

    Works for loops written in Python. A single long native call (one huge OpenCV operation) cannot be
    interrupted until it returns.
    """
    tid = threading.get_ident()
    finished = threading.Event()
    lock = threading.Lock()

    def watchdog():
        if not finished.wait(timeout_s):
            with lock:
                if not finished.is_set():
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), ctypes.py_object(ScriptTimeout))

    threading.Thread(target=watchdog, daemon=True, name="script-watchdog").start()
    try:
        exec(code_obj, env)
    finally:
        with lock:
            finished.set()
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)    # cancel one sent too late


@register_tool
class ScriptTool(VisionToolBase):
    category = "Logic Tools"
    tool_name = "Script"
    description = ("Runs your own Python with the image, the Val1 / Val2 inputs, OpenCV (cv2) and NumPy (np). "
                   "Set outputs['Result'], outputs['Status'] ('OK' passes, anything else fails), outputs['Image'] and add overlays. "
                   "get_global(name) / set_global(name, value) read and write the solution's global variables, and print() goes "
                   "to the Log output. A script that runs longer than its time limit is stopped.")

    def _init_ports(self):
        self._rebuild_ports([], [])

    def _base_inputs(self) -> Dict[str, ToolPort]:
        return {
            "Image": ToolPort("Image", DataType.IMAGE, "Input image"),
            "Val1": ToolPort("Val1", DataType.VALUE, "Numeric input 1"),
            "Val2": ToolPort("Val2", DataType.VALUE, "Numeric input 2"),
            "Data1": ToolPort("Data1", DataType.ANY, "Generic data input 1 (e.g. Tracks, Detections, JSON)"),
            "Data2": ToolPort("Data2", DataType.ANY, "Generic data input 2 (e.g. Bag Detections, Keypoints)"),
            "Data3": ToolPort("Data3", DataType.ANY, "Generic data input 3 (e.g. Shelf ROI, Telemetry)"),
            "Data4": ToolPort("Data4", DataType.ANY, "Generic data input 4 (e.g. Aisle ROI, Named_ROIs)"),
            "Trigger": ToolPort("Trigger", DataType.BOOLEAN, "Optional upstream boolean gate"),
        }

    def _base_outputs(self) -> Dict[str, ToolPort]:
        return {
            "Image": ToolPort("Image", DataType.IMAGE, "Pass-through or modified image"),
            "Result": ToolPort("Result", DataType.ANY, "Script result"),
            "Status": ToolPort("Status", DataType.STRING, "Script verdict"),
            "Log": ToolPort("Log", DataType.STRING, "Text the script printed"),
            "Text": ToolPort("Text", DataType.STRING, "Generated prompt or text output"),
            "System_Prompt": ToolPort("System_Prompt", DataType.STRING, "Generated system prompt"),
            "Trigger": ToolPort("Trigger", DataType.BOOLEAN, "Boolean trigger output"),
            "Value": ToolPort("Value", DataType.VALUE, "Numeric output (e.g. confidence for Condition Branch)"),
            "Data": ToolPort("Data", DataType.ANY, "Structured payload output"),
        }

    @staticmethod
    def _normalize_port_defs(raw: Any, reserved: set, prefix: str) -> List[Dict[str, str]]:
        if not isinstance(raw, (list, tuple)):
            return []
        used = set(reserved)
        cleaned: List[Dict[str, str]] = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            txt = re.sub(r"\s+", "_", str(item.get("name") or "").strip())
            txt = re.sub(r"[^a-zA-Z0-9_\-]", "", txt) or f"{prefix}_{idx + 1}"
            cand = txt
            n = 2
            while cand in used:
                cand = f"{txt}_{n}"
                n += 1
            used.add(cand)
            ptype = str(item.get("type") or "ANY").strip().upper()
            if ptype not in _SCRIPT_PORT_TYPES:
                ptype = "ANY"
            cleaned.append({"name": cand, "type": ptype})
        return cleaned

    def _rebuild_ports(self, raw_inputs: Any, raw_outputs: Any):
        inputs = self._base_inputs()
        outputs = self._base_outputs()
        cin = self._normalize_port_defs(raw_inputs, set(inputs.keys()), "In")
        cout = self._normalize_port_defs(raw_outputs, set(outputs.keys()), "Out")
        for p in cin:
            inputs[p["name"]] = ToolPort(p["name"], _SCRIPT_PORT_TYPES[p["type"]], f"Custom input ({p['type']})")
        for p in cout:
            outputs[p["name"]] = ToolPort(p["name"], _SCRIPT_PORT_TYPES[p["type"]], f"Custom output ({p['type']})")
        self.inputs = inputs
        self.outputs = outputs
        return cin, cout

    def set_param(self, key: str, value: Any):
        if key == "custom_inputs":
            cin, _ = self._rebuild_ports(value, self.parameters.get("custom_outputs", []))
            self.parameters["custom_inputs"] = cin
            return
        if key == "custom_outputs":
            _, cout = self._rebuild_ports(self.parameters.get("custom_inputs", []), value)
            self.parameters["custom_outputs"] = cout
            return
        super().set_param(key, value)

    def load_dict(self, data: Dict[str, Any]):
        super().load_dict(data)
        cin, cout = self._rebuild_ports(self.parameters.get("custom_inputs", []), self.parameters.get("custom_outputs", []))
        self.parameters["custom_inputs"] = cin
        self.parameters["custom_outputs"] = cout

    def _init_parameters(self):
        default_code = (
            "# inputs:  context['Image'], context['Val1'], context['Val2']\n"
            "# outputs: outputs['Result'], outputs['Status'] ('OK' passes), outputs['Image'], overlays\n"
            "# helpers: get_global('name', default), set_global('name', value), print(...), cv2, np\n\n"
            "v1 = context.get('Val1', 0.0)\n"
            "v2 = context.get('Val2', 0.0)\n"
            "calc = v1 * 2.5 + v2\n"
            "outputs['Result'] = calc\n"
            "outputs['Status'] = 'OK' if calc > 0 else 'NG'\n"
            "overlays.append({'type': 'text', 'text': f'Script Calc: {calc:.2f}', 'pt': (20, 100), 'color': (255, 200, 0)})\n"
        )
        self.parameters = {
            "code": default_code,
            "timeout_ms": 5000,      # a script still running after this is stopped
            "custom_inputs": [],
            "custom_outputs": [],
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        code = str(self.get_param("code", "") or "")
        img = context.get("Image")
        if not hasattr(self, "_script_state"):
            self._script_state = {}

        outputs: Dict[str, Any] = {
            "Image": img,
            "Result": 0.0,
            "Status": "OK",
            "Log": "",
            "Text": "",
            "System_Prompt": "",
            "Trigger": False,
            "Value": 0.0,
            "Data": None,
        }
        for p in self.get_param("custom_outputs", []) or []:
            if isinstance(p, dict) and p.get("name"):
                outputs.setdefault(str(p["name"]), _PORT_DEFAULTS.get(str(p.get("type", "ANY")).upper()))
        overlays: List[Dict[str, Any]] = []
        log: List[str] = []

        # The flow hands every module the solution's global variables (the same dict, so writes persist).
        gvars = (context.get("global") or {}).get("globals")
        if not isinstance(gvars, dict):
            gvars = {}

        def _print(*args, sep=" ", end="\n", **_ignored):
            log.append(sep.join(str(a) for a in args) + end)

        # One namespace for globals *and* locals: with a separate locals dict, functions and
        # comprehensions defined by the script cannot see `np`, `cv2`, `context`, ...
        script_env = {
            "cv2": cv2,
            "np": np,
            "time": time,
            "base64": base64,
            "json": json,
            "math": math,
            "re": re,
            "deque": deque,
            "state": self._script_state,
            "context": context,
            "outputs": outputs,
            "overlays": overlays,
            "get_global": lambda name, default=None: gvars.get(name, default),
            "set_global": lambda name, value: gvars.__setitem__(name, value),
            "print": _print,
        }

        timeout_ms = max(100.0, self.as_float(self.get_param("timeout_ms", 5000), 5000.0))
        try:
            run_with_deadline(compile(code, "<script>", "exec"), script_env, timeout_ms / 1000.0)
            outputs["Log"] = "".join(log)
            result_image = outputs.get("Image")
            if result_image is not None and not isinstance(result_image, np.ndarray):
                return ToolExecutionResult(
                    status=ToolStatus.ERROR,
                    message=(f"Script Error: outputs['Image'] must be a NumPy image (an array), "
                             f"not {type(result_image).__name__}"),
                    outputs={**outputs, "Image": img}, overlays=overlays)
            st = ToolStatus.OK if outputs.get("Status") == "OK" else ToolStatus.NG
            return ToolExecutionResult(
                status=st,
                message=f"Script executed. Result: {outputs.get('Result')}",
                outputs=outputs,
                overlays=overlays
            )
        except ScriptTimeout:
            outputs["Log"] = "".join(log)
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=(f"Script stopped: it ran longer than its time limit ({timeout_ms:.0f} ms). "
                         f"Check for a loop that never ends, or raise Timeout ms."),
                outputs=outputs, overlays=overlays)
        except Exception as e:
            outputs["Log"] = "".join(log)
            line = ""
            if isinstance(e, SyntaxError) and e.lineno:
                line = f" (line {e.lineno})"
            else:
                for frame in reversed(traceback.extract_tb(e.__traceback__)):
                    if frame.filename == "<script>":
                        line = f" (line {frame.lineno})"
                        break
            detail = e.msg if isinstance(e, SyntaxError) else str(e)
            return ToolExecutionResult(
                status=ToolStatus.ERROR,
                message=f"Script Error: {type(e).__name__}: {detail}{line}",
                outputs=outputs,
                overlays=overlays
            )
