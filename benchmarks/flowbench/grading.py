"""FlowBench grader: partial credit for a flow spec, checked by Vision Studio's own tools over MCP.

score_v1 = 0.4 * spec validates cleanly
         + 0.3 * dry run on synthetic input succeeds
         + 0.3 * share of the required tools present

v2 (the reward from run 3 on): tasks with labelled images also check the flow's verdict, because a flow can be
valid and run cleanly yet decide wrongly. For those tasks:
score = 0.25 valid + 0.15 dry run + 0.2 coverage + 0.2 OK on the should-pass image + 0.2 NG on the should-fail image.
Other tasks keep score_v1: their request does not pin down ROI, model or geometry, so a fixed image would be unfair.
"""
import asyncio
import json
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional

import fastmcp

HERE = os.path.dirname(os.path.abspath(__file__))
STUDIO_PYTHON = os.environ.get("FLOWBENCH_PYTHON", r"C:\Users\winch\AppData\Local\Programs\Python\Python312\python.exe")
# Only tasks where the reference recipe itself gets both images right (checked in sanity_check.py).
LABELLED = {t: (os.path.join(HERE, "labelled", f"{t}_pass.png"), os.path.join(HERE, "labelled", f"{t}_fail.png"))
            for t in ("color_check", "defect_check")}
LOG = os.path.join(HERE, "results", "answers.jsonl")


def extract_spec(answer: Any) -> Optional[Dict[str, Any]]:
    if isinstance(answer, dict):
        return answer
    text = str(answer or "")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):  # first decodable object that looks like a flow spec
        if ch != "{":
            continue
        try:
            spec, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(spec, dict) and "modules" in spec:
            return spec
    return None


def _payload(result: Any) -> Dict[str, Any]:
    data = getattr(result, "structured_content", None) or getattr(result, "data", None)
    if isinstance(data, dict):
        return data.get("result", data) if set(data) == {"result"} else data
    for block in getattr(result, "content", []) or []:
        try:
            return json.loads(block.text)
        except Exception:
            pass
    return {}


async def verdicts(spec: Dict[str, Any], images) -> Dict[str, str]:
    """Flow verdict (OK / NG / Error ...) per image, run in Vision Studio's own Python."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(spec, f)
    try:
        proc = await asyncio.create_subprocess_exec(
            STUDIO_PYTHON, os.path.join(HERE, "verdict_check.py"), f.name, *images,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        return json.loads(out.decode().strip().splitlines()[-1])
    finally:
        os.unlink(f.name)


def _log(task_id: str, answer: Any, result: Dict[str, Any], spec: Any) -> None:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "model": os.environ.get("FLOWBENCH_MODEL", ""),
                            "task": task_id, "score": result["score"], "info": result["info"],
                            "spec": spec, "answer": str(answer)[:6000]}) + "\n")


async def grade(answer: Any, required: List[str], mcp_url: str, task_id: str = "") -> Dict[str, Any]:
    spec = extract_spec(answer)
    try:
        result = await _grade(spec, required, mcp_url, task_id)
    except Exception as exc:  # a grader crash must be visible, not a silent 0
        result = {"score": 0.0, "info": {"reason": f"grader error: {exc!r}"}}
    _log(task_id, answer, result, spec)
    return result


async def _grade(spec: Any, required: List[str], mcp_url: str, task_id: str = "") -> Dict[str, Any]:
    if spec is None:
        return {"score": 0.0, "info": {"reason": "no JSON flow spec in the answer", "score_v1": 0.0}}
    tools = [m.get("tool") for m in spec.get("modules", []) if isinstance(m, dict)]
    coverage = sum(t in tools for t in required) / len(required)
    async with fastmcp.Client(mcp_url) as client:
        valid = _payload(await client.call_tool("validate_flow", {"spec": spec}, raise_on_error=False))
        dry = _payload(await client.call_tool("dry_run", {"spec": spec}, raise_on_error=False))
    errors = [i for i in valid.get("issues", []) if i.get("severity") == "error"]
    valid_ok, dry_ok = bool(valid.get("ok")), bool(dry.get("ok"))
    score_v1 = round(0.4 * valid_ok + 0.3 * dry_ok + 0.3 * coverage, 3)
    info = {"valid": valid_ok, "dry_run": dry_ok, "tool_coverage": round(coverage, 2), "score_v1": score_v1,
            "tools_used": tools, "missing_tools": [t for t in required if t not in tools],
            "errors": [e.get("code") for e in errors][:5]}
    score = score_v1
    if task_id in LABELLED:
        good, bad = LABELLED[task_id]
        seen = await verdicts(spec, [good, bad]) if valid_ok else {}
        pass_ok = seen.get(os.path.basename(good)) == "OK"
        fail_ok = seen.get(os.path.basename(bad)) == "NG"
        info["verdicts"] = seen or "not run (invalid flow)"
        info["verdict_correct"] = f"{int(pass_ok) + int(fail_ok)}/2"
        score = round(0.25 * valid_ok + 0.15 * dry_ok + 0.2 * coverage + 0.2 * pass_ok + 0.2 * fail_ok, 3)
    return {"score": score, "info": info}
