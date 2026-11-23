"""Grader blind-spot probe: grade the model's color_check flow after fixing only its 2 syntax errors.

The model's threshold (Color_Ratio >= 0.2) differs from the recipe (>= 5.0), so a flow that is
valid and runs can still pass parts that should fail. Run with the HUD tool's Python.
"""
import asyncio, json, os, socket, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from grading import grade
STUDIO_PYTHON = os.environ.get("FLOWBENCH_PYTHON", r"C:\Users\winch\AppData\Local\Programs\Python\Python312\python.exe")
os.environ["FLOWBENCH_MODEL"] = "blindspot-probe"

async def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    proc = subprocess.Popen([STUDIO_PYTHON, os.path.join(HERE, "serve_mcp.py"), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try: socket.create_connection(("127.0.0.1", port), 0.25).close(); break
        except OSError: time.sleep(0.25)
    try:
        spec = json.load(open(os.path.join(HERE, "results", "model_color_check_2fixes.json"), encoding="utf-8"))
        print(await grade(json.dumps(spec), ["Image Source", "Color Extraction", "Condition Branch"],
                          f"http://127.0.0.1:{port}/mcp", "color_check_blindspot"))
    finally:
        proc.terminate()
asyncio.run(main())
