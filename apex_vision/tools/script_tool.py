"""
Script and Custom Logic Tools.
Matches the reference product Global Script / Python Script Tool.
Allows industrial vision engineers to write custom Python/OpenCV logic inline.
"""
import ctypes
import threading
import traceback
from typing import Dict, Any, List
import numpy as np
import cv2
from apex_vision.core.base_tool import VisionToolBase, ToolExecutionResult, ToolStatus, ToolPort, DataType
from apex_vision.core.registry import register_tool


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
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Input image")
        self.inputs["Val1"] = ToolPort("Val1", DataType.VALUE, "Numeric input 1")
        self.inputs["Val2"] = ToolPort("Val2", DataType.VALUE, "Numeric input 2")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through or modified image")
        self.outputs["Result"] = ToolPort("Result", DataType.ANY, "Script result")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "Script verdict")
        self.outputs["Log"] = ToolPort("Log", DataType.STRING, "Text the script printed")

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
        }

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        code = str(self.get_param("code", "") or "")
        img = context.get("Image")

        outputs: Dict[str, Any] = {
            "Image": img,
            "Result": 0.0,
            "Status": "OK",
            "Log": ""
        }
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
