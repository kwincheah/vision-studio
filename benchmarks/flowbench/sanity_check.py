"""Check the grader before trusting any model score.

For every task: the matching recipe spec should score 1.0, a broken spec should score low,
and a non-JSON answer should score 0. For the labelled tasks, a "wrong decision" flow (valid, runs, but its
threshold can never fail) should lose the verdict points. Run with the HUD tool's Python (it has fastmcp).
"""
import asyncio
import copy
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import grading  # noqa: E402
from grading import LABELLED, STUDIO_PYTHON, grade  # noqa: E402
from tasks import TASKS  # noqa: E402

grading.LOG = os.path.join(HERE, "results", "sanity.jsonl")  # keep sanity rows out of the run logs
RECIPES = os.path.join(HERE, "..", "..", "apex_vision", "flowgen", "recipes")


def wrong_decision(task_id, spec):
    """Same tools and links, but a decision that passes everything (the run-1 color_check mistake, made total)."""
    s = copy.deepcopy(spec)
    for m in s["modules"]:
        p = m.setdefault("params", {})
        if m["tool"] == "Color Extraction":
            p["min_ratio"] = 0.0
        if m["tool"] == "Condition Branch":
            p.update(operator=">=", threshold_low=-1e9)
    return s


async def main() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    proc = subprocess.Popen([STUDIO_PYTHON, os.path.join(HERE, "serve_mcp.py"), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            socket.create_connection(("127.0.0.1", port), 0.25).close(); break
        except OSError:
            time.sleep(0.25)
    url = f"http://127.0.0.1:{port}/mcp"
    rows = []
    try:
        for task_id, (_, required) in TASKS.items():
            spec = json.load(open(os.path.join(RECIPES, task_id + ".json"), encoding="utf-8"))["spec"]
            broken = copy.deepcopy(spec); broken["links"] = broken.get("links", [])[:-1]
            broken["modules"][-1]["tool"] = "Conditon Branch"  # typo'd tool name
            good = await grade(json.dumps(spec), required, url, task_id)
            bad = await grade(json.dumps(broken), required, url, task_id)
            none = await grade("I could not build it.", required, url, task_id)
            wrong = await grade(json.dumps(wrong_decision(task_id, spec)), required, url, task_id) \
                if task_id == "color_check" else None
            rows.append((task_id, good, bad, none, wrong))
    finally:
        proc.terminate()
    print(f"{'task':<18} {'recipe':>7} {'broken':>7} {'no-json':>8} {'wrong-decision':>15}  recipe verdicts")
    for task_id, good, bad, none, wrong in rows:
        w = f"{wrong['score']} (v1 {wrong['info']['score_v1']})" if wrong else "-"
        print(f"{task_id:<18} {good['score']:>7} {bad['score']:>7} {none['score']:>8} {w:>15}  "
              f"{good['info'].get('verdicts', '')}")


asyncio.run(main())
