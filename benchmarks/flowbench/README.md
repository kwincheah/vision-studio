# FlowBench

A [HUD](https://docs.hud.ai) environment that asks an agent to build an Apex Vision Studio inspection flow from a
plain-language request, using the app's own flowgen MCP tools (`search_tools`, `get_tool_spec`, `search_docs`,
`read_doc`, `validate_flow`, `dry_run`, `build_flow_xml`, `save_flow_xml`).

| File | What it does |
|---|---|
| `tasks.py` | HUD environment: 7 tasks (one per flowgen recipe), starts the MCP server per rollout, grades the answer |
| `serve_mcp.py` | Runs `apex_vision.flowgen.mcp_server` over streamable HTTP (HUD needs a URL, not stdio); exits with its parent |
| `grading.py` | v1: 0.4 × `validate_flow` OK + 0.3 × `dry_run` OK + 0.3 × required-tool coverage. v2 adds a PASS/FAIL check on labelled images for color_check and defect_check. Logs every answer |
| `verdict_check.py` | Grader helper: runs a spec on given images in Vision Studio's Python and returns OK / NG per image |
| `make_labelled_images.py` | Builds the should-pass / should-fail images in `labelled/` |
| `sanity_check.py` | Grader check without a model: recipes 1.00, broken copy ~0.13-0.23, non-JSON 0, a never-failing color_check flow 0.80 |
| `blindspot_check.py` | Shows the run-1 qwen color_check flow (2 syntax fixes) scoring 1.00 under grader v1 despite its wrong threshold units |
| `capture_flow.py` | Opens a spec in Vision Studio offscreen and saves a screenshot plus the solution XML |
| `make_report.py` | Builds `results/REPORT.md` and `results/report.html` from the answer logs and eval logs |

## Run

```bash
export PATH="$HOME/.local/bin:$PATH"          # HUD CLI (uv tool install hud)
python3 -m pip install mcp                     # Vision Studio's Python also needs its normal requirements
FLOWBENCH_MODEL=qwen3-4b hud eval tasks.py openai_compatible -m qwen3-4b-16k \
  --config base_url=http://localhost:11434/v1 --config api_key=ollama --all --max-steps 15 --max-concurrent 1 --yes -vv \
  > results/run1_qwen3-4b.log 2>&1
```

OpenRouter (run 3): put the key in `OPENAI_API_KEY` for this shell only, then

```bash
FLOWBENCH_MODEL=deepseek-v4-flash hud eval tasks.py openai_compatible -m deepseek/deepseek-v4-flash   --config base_url=https://openrouter.ai/api/v1 --all --group 3 --max-steps 20 --max-concurrent 1 --yes -vv   > results/run3_deepseek-v4-flash.log 2>&1
```

After a run, rename `results/answers.jsonl` to `results/answers_runN.jsonl` and run `python make_report.py`.

Set `FLOWBENCH_PYTHON` if Vision Studio's interpreter is not the default path in `tasks.py`, and
`FLOWBENCH_PROMPT=strict` for the stricter prompt used in run 2. Results: see `results/REPORT.md`.
