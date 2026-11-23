"""FlowBench: can an agent build a working Apex Vision Studio inspection flow from a plain request?

The agent gets Vision Studio's flow-generation MCP tools (search_tools, get_tool_spec, search_docs,
read_doc, validate_flow, dry_run, build_flow_xml, save_flow_xml) and must answer with a flow spec.
Run:  hud eval tasks.py <agent> --all --group 3 --yes
"""
import asyncio
import os
import socket
import subprocess
import sys

from hud import Environment
from hud.capabilities import Capability

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from grading import grade  # noqa: E402

# Vision Studio's own interpreter (has OpenCV, mcp, ...); the HUD CLI runs in its own isolated Python.
STUDIO_PYTHON = os.environ.get("FLOWBENCH_PYTHON", r"C:\Users\winch\AppData\Local\Programs\Python\Python312\python.exe")

env = Environment(name="flowbench")
_state = {}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@env.initialize
async def start_flowgen_server() -> None:
    port = _free_port()
    _state["proc"] = subprocess.Popen([STUDIO_PYTHON, os.path.join(HERE, "serve_mcp.py"), str(port)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):  # imports OpenCV etc., so give it up to ~30 s
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                break
        except OSError:
            await asyncio.sleep(0.25)
    _state["url"] = f"http://127.0.0.1:{port}/mcp"
    env.add_capability(Capability.mcp(name="flowgen", url=_state["url"]))


@env.shutdown
async def stop_flowgen_server() -> None:
    proc = _state.get("proc")
    if proc and proc.poll() is None:
        proc.terminate()


INSTRUCTIONS = (
    "You are building an inspection flow in Apex Vision Studio using the flowgen tools.\n"
    "Workflow: search_docs / search_tools to find a matching recipe and tools, get_tool_spec for exact "
    "port and parameter names, draft a spec {name, modules:[{id, tool, params}], links:[{from, from_port, "
    "to, to_port}]}, call validate_flow and fix every error until it returns ok, then dry_run it.\n"
    "Finish by replying with ONLY the final flow spec as one JSON object, nothing else."
)

# Ablation (run 2): FLOWBENCH_PROMPT=strict makes tool use and validation explicit requirements.
# The default prompt above stays unchanged so run 1 remains reproducible.
STRICT = (
    "\nRules: tool names exist only in this application, so never guess them. Before writing any module you "
    "MUST call search_tools (or search_docs) and use the exact tool names it returns, and get_tool_spec for "
    "their port and parameter names. You MUST call validate_flow on your final spec and only answer once it "
    "returns ok."
)
if os.environ.get("FLOWBENCH_PROMPT") == "strict":
    INSTRUCTIONS += STRICT

# (task id, plain-language request, tools a correct flow must contain)
TASKS = {
    "blob_count": ("Count the small parts on a backlit tray. Clean the image up first, then pass the tray only "
                   "if exactly 5 parts are found.",
                   ["Image Source", "Image Binarization", "BLOB Analysis", "Condition Branch"]),
    "color_check": ("Check that a green sticker is present: pass only if enough of the image is green.",
                    ["Image Source", "Color Extraction", "Condition Branch"]),
    "defect_check": ("Inspect a region of a metal surface for scratches or dirt and fail the part if any "
                     "defect is found.",
                     ["Image Source", "Defect Detection", "Condition Branch"]),
    "object_detection": ("Use a neural-network object detector to find bottles in the image and pass only "
                         "if exactly 6 are found.",
                         ["Image Source", "Object Detection", "Condition Branch"]),
    "point_to_point": ("Find two edge points on a part and measure the distance between them; fail if it is "
                       "outside 95 to 105 pixels.",
                       ["Image Source", "Caliper", "P2P Measure", "Condition Branch"]),
    "read_label": ("Read the serial number printed on a label and fail the part unless it starts with 'SN-'.",
                   ["Image Source", "OCR Recognition", "Branch String"]),
    "width_measurement": ("Measure the width of a part between its two edges and pass only if it is between "
                          "190 and 210 pixels.",
                          ["Image Source", "Caliper", "Condition Branch"]),
}


@env.template(description="Build a Vision Studio flow from a plain-language inspection request")
async def build_flow(task_id: str = "defect_check"):
    request, required = TASKS[task_id]
    answer = yield f"{INSTRUCTIONS}\n\nInspection request: {request}"
    yield await grade(answer, required, _state["url"], task_id)


tasks = [build_flow(task_id=t) for t in TASKS]
