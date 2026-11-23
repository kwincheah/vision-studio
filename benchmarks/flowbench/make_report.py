"""Turn FlowBench runs (answers_runN.jsonl + each run's -vv eval log) into results/REPORT.md and results/report.html."""
import collections
import html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
# (label, answers file, eval log, where the model ran)
RUNS = [
    ("Run 1 · qwen3:4b · default prompt", "answers_run1.jsonl", "run1_qwen3-4b.log", "local Ollama, CPU"),
    ("Run 2 · qwen3:4b · strict prompt", "answers_run2.jsonl", "run2_qwen3-4b_strict.log", "local Ollama, CPU"),
    ("Run 3 · DeepSeek V4 Flash · default prompt · 3 tries per task", "answers_run3.jsonl",
     "run3_deepseek-v4-flash.log", "OpenRouter"),
]
SPEC_CALL = re.compile(r"'name': '(validate_flow|dry_run|build_flow_xml|save_flow_xml)', 'arguments': (.*)")
AGENT_CALL = re.compile(r"method='tools/call' params=\{'_meta': \{'hud/trace-id'.*?'name': '([a-z_]+)'")


def v1(r):
    return r["info"].get("score_v1", r["score"])  # runs 1-2 were graded before v2, so their score is v1


def spec_kind(args: str) -> str:
    """What the agent actually put in the `spec` argument of a spec-taking tool call."""
    if args.startswith("{'spec': {}"):
        return "empty object"
    if args.startswith("{'spec': ''"):
        return "empty string"
    if args.startswith("{'spec': '") and "DSML" in args[:60]:
        return "leaked tool-call markup"
    if args.startswith("{'spec': '"):
        return "other string"
    return "real flow" if "'modules'" in args[:400] else "other"


def load(label, answers, log, where):
    rows = [json.loads(line) for line in open(os.path.join(OUT, answers), encoding="utf-8")]
    segments, cur = [], None  # the log is sequential (max-concurrent 1); each rollout starts at "step 1/"
    for line in open(os.path.join(OUT, log), encoding="utf-8", errors="replace"):
        if "tool_agent - step 1/" in line:
            cur = {"calls": [], "steps": 0, "spec_args": collections.Counter()}
            segments.append(cur)
        if cur is None:
            continue
        m = re.search(r"tool_agent - step (\d+)/", line)
        if m:
            cur["steps"] = int(m.group(1))
        m = AGENT_CALL.search(line)
        if m:
            cur["calls"].append(m.group(1))
            m2 = SPEC_CALL.search(line)
            if m2:
                cur["spec_args"][spec_kind(m2.group(2))] += 1
    for r, seg in zip(rows, segments):
        r["calls"], r["steps"], r["spec_args"] = seg["calls"], seg["steps"], dict(seg["spec_args"])
    n = len(rows)
    labelled = [r for r in rows if "verdict_correct" in r["info"]]
    s = {"label": label, "where": where, "model": rows[0].get("model"), "rollouts": n,
         "mean_score": round(sum(r["score"] for r in rows) / n, 3),
         "mean_score_v1": round(sum(v1(r) for r in rows) / n, 3),
         "graded_v2": bool(labelled),
         "valid": sum(bool(r["info"].get("valid")) for r in rows),
         "dry_run_ok": sum(bool(r["info"].get("dry_run")) for r in rows),
         "mean_tool_coverage": round(sum(r["info"].get("tool_coverage", 0) for r in rows) / n, 2),
         "rollouts_that_called_tools": sum(bool(r.get("calls")) for r in rows),
         "rollouts_that_validated": sum("validate_flow" in r.get("calls", []) for r in rows),
         "verdicts_correct": f"{sum(int(r['info']['verdict_correct'][0]) for r in labelled)}/{2 * len(labelled)}"
         if labelled else "n/a",
         "out_of_steps_no_answer": sum(r.get("steps") == r.get("max_steps", 20) and "reason" in r["info"] for r in rows)
         if any(r.get("steps", 0) >= 20 for r in rows) else 0,
         "spec_args": dict(sum((collections.Counter(r.get("spec_args", {})) for r in rows), collections.Counter())),
         "error_codes": dict(collections.Counter(e for r in rows for e in r["info"].get("errors", [])))}
    return s, rows


runs = [load(*r) for r in RUNS
        if os.path.exists(os.path.join(OUT, r[1])) and os.path.exists(os.path.join(OUT, r[2]))]
json.dump([{"summary": s, "rows": rows} for s, rows in runs],
          open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), indent=1)

BLINDSPOT = ("In run 1 the model's color_check flow failed on two syntax slips ('green' instead of 'Green', and a "
             "link missing its from_port). Fixing only those two makes it score a perfect 1.00 under grader v1, yet "
             "its own decision step is wrong: Color_Ratio >= 0.2, while the tool reports percent and the recipe uses "
             ">= 5. On an image that is only 1% green that step says PASS; the flow still ends NG only because Color "
             "Extraction's default 5% minimum, which the model never set, catches it. v1 could not see any of this: "
             "validate_flow checks structure and the one synthetic dry-run image is 92% green. Grader v2 adds a "
             "should-pass and a should-fail image for color_check and defect_check (recipes get both right); a "
             "color_check flow whose decision can never fail now scores 0.80 instead of 1.00.")

COLS = ("| Run | Model | Mean score (reward) | Mean score, v1 formula | Valid | Dry run OK | Tool coverage | "
        "Used tools | Called validate_flow | Labelled verdicts right (submitted flows) |")
md = ["# FlowBench results", "",
      "HUD environment that gives an agent Apex Vision Studio's 8 flowgen MCP tools and asks it to build an "
      "inspection flow from a plain-language request (7 tasks).", "",
      "- Grader v1 (runs 1-2): 0.4 x validate_flow OK + 0.3 x dry run OK + 0.3 x required-tool coverage.",
      "- Grader v2 (run 3): same for 5 tasks; color_check and defect_check also check the flow's verdict on a "
      "should-pass and a should-fail image (0.25 valid + 0.15 dry run + 0.2 coverage + 0.2 + 0.2 verdicts). "
      "The v1 column lets all runs be compared on the same formula.",
      "- Sanity check: every recipe scores 1.00, a broken copy about 0.13-0.23, a non-JSON answer 0, and a color_check "
      "flow whose decision never fails 0.80 (v1 gave it 1.00).", "", COLS, "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
for s, _ in runs:
    n = s["rollouts"]
    md.append(f"| {s['label']} | {s['model']} ({s['where']}) | {s['mean_score']:.3f} | {s['mean_score_v1']:.3f} | "
              f"{s['valid']}/{n} | {s['dry_run_ok']}/{n} | {s['mean_tool_coverage']:.2f} | "
              f"{s['rollouts_that_called_tools']}/{n} | {s['rollouts_that_validated']}/{n} | {s['verdicts_correct']} |")
for s, rows in runs:
    md += ["", f"## {s['label']}", "", f"Validator error codes: {s['error_codes'] or 'none'}", "",
           "| Task | Score | v1 | Valid | Dry run | Coverage | Verdicts | Steps | Agent tool calls | Tools in final answer |",
           "|---|---:|---:|:-:|:-:|---:|:-:|---:|---|---|"]
    for r in rows:
        i = r["info"]
        calls = ", ".join(f"{k} x{v}" for k, v in collections.Counter(r.get("calls", [])).items()) or "none"
        md.append(f"| {r['task']} | {r['score']:.3f} | {v1(r):.3f} | {'yes' if i.get('valid') else 'no'} | "
                  f"{'yes' if i.get('dry_run') else 'no'} | {i.get('tool_coverage', 0):.2f} | {i.get('verdict_correct', '-')} | "
                  f"{r.get('steps', '')} | {calls} | {', '.join(i.get('tools_used', [])) or i.get('reason', '')} |")
FINDINGS = [
    ("qwen3:4b barely used the tools",
     "The tools reached the model (run 1 color_check called search_docs, get_tool_spec and search_tools and was the "
     "only answer with real tool names), but 13 of 14 rollouts answered in one step and invented tool names such as "
     "DefectInspector. A stricter prompt (run 2) made it 0 of 7."),
]
r3 = next(((s, rows) for s, rows in runs if s["model"] == "deepseek-v4-flash"), None)
if r3:
    s3, rows3 = r3
    done = [r for r in rows3 if "reason" not in r["info"]]
    stuck = [r for r in rows3 if "reason" in r["info"]]
    sa = collections.Counter()
    for r in stuck:
        sa.update(r.get("spec_args", {}))
    FINDINGS.append((
        "DeepSeek V4 Flash: every flow it submitted scored 1.00; its failures were broken tool calls",
        f"{len(done)} of {len(rows3)} rollouts submitted a flow and every one scored 1.00 (labelled verdicts "
        f"{s3['verdicts_correct']} right). The other {len(stuck)} hit the 20-step limit without an answer "
        f"(defect_check 0 of 3). In those rollouts the flow never reached the tools: the spec argument arrived as an "
        f"empty object ({sa['empty object']} calls), an empty string ({sa['empty string']}) or DeepSeek's own "
        f"tool-call markup leaking into the argument, e.g. '<｜DSML｜parameter name=\"spec\" ...>' with a '{{ ... }}' "
        f"placeholder ({sa['leaked tool-call markup']}), against {sa['real flow']} calls with a real flow. The "
        "validator answered \"'modules' must be a non-empty list\" each time and the model repeated the same call. "
        "Environment fixes to test next: take the spec as a JSON string, say plainly that the argument arrived empty, "
        "and stop a rollout after several identical failing calls."))
FINDINGS.append(("Grader blind spot, and the fix", BLINDSPOT))
for title, text in FINDINGS:
    md += ["", f"## {title}", "", text]
md += ["", "Screenshots: `report.png` (this page), `deepseek_*.png` (DeepSeek flows in Vision Studio), "
       "`model_color_check_2fixes.png` (the run-1 qwen flow, 2 syntax fixes only), `reference_color_check.png` (recipe)."]
open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")


def pill(ok, text=None):
    return f'<span class="pill {"ok" if ok else "bad"}">{text or ("yes" if ok else "no")}</span>'


sections = []
for s, rows in runs:
    n = s["rollouts"]
    trs = []
    for r in rows:
        i = r["info"]
        calls = ", ".join(f"{k} ×{v}" for k, v in collections.Counter(r.get("calls", [])).items()) or "<em>none</em>"
        tools = ", ".join(html.escape(t) for t in i.get("tools_used", [])) or html.escape(i.get("reason", ""))
        vc = i.get("verdict_correct")
        trs.append(f"<tr><td class=task>{r['task']}</td><td class=num><div class=bar>"
                   f"<span style='width:{int(r['score'] * 100)}%'></span></div>{r['score']:.2f}</td>"
                   f"<td>{pill(i.get('valid'))}</td><td>{pill(i.get('dry_run'))}</td>"
                   f"<td class=num>{i.get('tool_coverage', 0):.2f}</td>"
                   f"<td>{pill(vc == '2/2', vc) if vc else '–'}</td><td class=small>{calls}</td>"
                   f"<td class=small>{tools}</td></tr>")
    v1note = f"<span>v1 formula: {s['mean_score_v1']:.2f}</span>" if s["graded_v2"] else ""
    sections.append(
        f"<h2>{html.escape(s['label'])} <small>({html.escape(s['where'])})</small></h2><div class=kpis>"
        f"<div class=kpi><b>{s['mean_score']:.2f}</b><span>mean score (0–1)</span>{v1note}</div>"
        f"<div class=kpi><b>{s['valid']}/{n}</b><span>flows that validate</span></div>"
        f"<div class=kpi><b>{s['mean_tool_coverage']:.2f}</b><span>required-tool coverage</span></div>"
        f"<div class=kpi><b>{s['rollouts_that_called_tools']}/{n}</b><span>runs where the agent used the tools</span></div>"
        f"<div class=kpi><b>{s['rollouts_that_validated']}/{n}</b><span>runs that called validate_flow</span></div>"
        f"<div class=kpi><b>{s['verdicts_correct']}</b><span>labelled verdicts right (submitted flows)</span></div></div>"
        "<div class=card><table><tr><th>Task</th><th>Score</th><th>Valid</th><th>Dry run</th><th>Coverage</th>"
        "<th>Verdicts</th><th>Agent tool calls</th><th>Tools in final answer</th></tr>" + "".join(trs) + "</table></div>")

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mut:#6b6b66;--line:#e4e3de;--ok:#1f7a4d;--okbg:#e3f3ea;--bad:#b3261e;
--badbg:#fbe7e5;--acc:#2f5bd3;--warnbg:#fff6e0;--warn:#8a5a00}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151514;--card:#1e1e1c;--ink:#ecebe6;--mut:#a3a29b;
--line:#33322f;--ok:#6fd19d;--okbg:#17352a;--bad:#ff8a80;--badbg:#3d1a18;--acc:#8aa8ff;--warnbg:#3a2e12;--warn:#f3c969}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px} h1{margin:0 0 4px;font-size:26px} h2{font-size:18px;margin:28px 0 10px}
h2 small{font-weight:400;color:var(--mut);font-size:14px}
.sub{color:var(--mut);margin:0 0 8px} .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px} .kpi b{display:block;font-size:24px}
.kpi span{display:block;color:var(--mut);font-size:13px} .card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow-x:auto}
table{border-collapse:collapse;width:100%} th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)} .num{white-space:nowrap} .small{font-size:13px}
.task{font-weight:600;white-space:nowrap}
.bar{display:inline-block;width:60px;height:7px;background:var(--line);border-radius:4px;margin-right:8px;vertical-align:middle}
.bar span{display:block;height:100%;background:var(--acc);border-radius:4px}
.pill{font-size:12px;padding:2px 8px;border-radius:99px;white-space:nowrap} .ok{color:var(--ok);background:var(--okbg)} .bad{color:var(--bad);background:var(--badbg)}
.finding{background:var(--warnbg);border-left:4px solid var(--warn);border-radius:8px;padding:12px 16px;margin-top:12px}
.note{color:var(--mut);font-size:13px}"""

page = ("<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>FlowBench Results</title><style>{CSS}</style></head><body><main>"
        "<h1>FlowBench: agents building Apex Vision Studio flows</h1>"
        "<p class=sub>HUD environment · Vision Studio's 8 flowgen MCP tools · 7 inspection tasks</p>"
        "<p class=note>Grader v1 (runs 1–2): 0.4 × validate_flow OK + 0.3 × dry run OK + 0.3 × required-tool coverage. "
        "Grader v2 (run 3) also checks the flow's PASS/FAIL on a should-pass and a should-fail image for color_check "
        "and defect_check. Sanity check: recipes score 1.00, broken copies about 0.13–0.23, non-JSON 0.</p>"
        + "".join(sections)
        + "<h2>What we learned</h2>"
        + "".join(f"<div class=finding><b>{html.escape(t)}.</b> {html.escape(x)}</div>" for t, x in FINDINGS)
        + "</main></body></html>")
open(os.path.join(OUT, "report.html"), "w", encoding="utf-8").write(page)
for s, _ in runs:
    print(json.dumps(s))
