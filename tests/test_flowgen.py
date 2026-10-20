"""AI flow generation: catalogue, spec validation / building, reference retrieval and the assistant loop
(driven by a scripted fake Anthropic client - no network)."""
import json
import os
from types import SimpleNamespace

import pytest

from vm_clone.core.pipeline import SolutionManager
from vm_clone.flowgen import api, catalog, docs, reference_gen
from vm_clone.flowgen.agent import FlowAgent, _tool_defs
from vm_clone.flowgen.spec import build_flow, has_errors, spec_to_xml, validate_spec

GOOD = {"name": "Blur_Count", "modules": [
    {"id": "src", "tool": "Image Source"},
    {"id": "blur", "tool": "Image Filter", "params": {"filter_type": "Gaussian", "kernel_size": 5}},
    {"id": "bin", "tool": "Image Binarization"},
    {"id": "blobs", "tool": "BLOB Analysis"}],
    "links": [{"from": "src", "from_port": "Image", "to": "blur", "to_port": "Image"},
              {"from": "blur", "from_port": "Image", "to": "bin", "to_port": "Image"},
              {"from": "bin", "from_port": "Image", "to": "blobs", "to_port": "Image"}]}


def codes(spec):
    return {i["code"] for i in validate_spec(spec)}


# ---------------------------------------------------------------- catalogue
def test_catalogue_covers_every_registered_tool_with_ports_and_parameters():
    from vm_clone.core.registry import list_all_tools
    cat = {c["tool"]: c for c in catalog.full_catalog()}
    assert set(cat) == set(list_all_tools()) and len(cat) >= 40
    assert cat["Caliper"]["outputs"]["Edge1"] == "POINT"
    assert cat["Caliper"]["parameters"]["polarity"]["choices"] == ["Any", "Dark to light", "Light to dark"]
    assert all(c["description"] for c in cat.values())


def test_enum_choices_are_per_tool_so_the_same_parameter_name_can_mean_different_things():
    # `operation` is a morphology choice on Image Morphology but +,-,*,/ on Variable Calculation
    assert catalog.tool_spec("Variable Calculation")["parameters"]["operation"]["choices"] == ["+", "-", "*", "/", "Scale"]
    assert "Open" in catalog.tool_spec("Image Morphology")["parameters"]["operation"]["choices"]
    assert catalog.tool_spec("Caliper")["parameters"]["line_p1"]["editor"] == "point"
    assert catalog.tool_spec("Template Match")["parameters"]["min_score"]["max"] == 1


def test_catalogue_does_not_leak_the_install_path():
    text = json.dumps(catalog.full_catalog())
    assert os.path.dirname(os.path.dirname(os.path.abspath(catalog.__file__))) not in text.replace("\\\\", "\\")


def test_keyword_search_finds_the_right_tool():
    names = [h["tool"] for h in catalog.search_tools("measure distance between two points")]
    assert "P2P Measure" in names[:3]
    assert [h["tool"] for h in catalog.search_tools("", category="Calibration")] and \
        all(h["category"] == "Calibration" for h in catalog.search_tools("", category="Calibration"))


# ---------------------------------------------------------------- validation
def test_a_good_spec_is_clean_and_round_trips_through_the_apps_own_loader():
    assert not has_errors(validate_spec(GOOD))
    xml, issues = spec_to_xml(GOOD, "Demo")
    sol = SolutionManager.from_xml(xml)
    flow = sol.flows["Blur_Count"]
    assert len(flow.nodes) == 4 and len(flow.connections) == 3
    assert flow.nodes["blur"].get_param("kernel_size") == 5
    assert flow.node_positions["bin"][0] > flow.node_positions["src"][0]          # laid out left to right
    assert not any(i["severity"] == "error" for i in issues)


@pytest.mark.parametrize("mutate,code", [
    (lambda s: s["modules"].append({"id": "x", "tool": "Blur"}), "unknown_tool"),
    (lambda s: s["modules"][1]["params"].update(sigma_x=1), "unknown_param"),
    (lambda s: s["modules"][1]["params"].update(filter_type="Box"), "bad_param"),
    (lambda s: s["modules"][1]["params"].update(kernel_size="big"), "bad_param"),
    (lambda s: s["modules"][1]["params"].update(kernel_size=10 ** 15), "bad_param"),
    (lambda s: s["modules"].append({"id": "src", "tool": "Histogram"}), "duplicate_id"),
    (lambda s: s["links"].append({"from": "src", "from_port": "Image", "to": "blobs", "to_port": "Image"}), "input_taken"),
    (lambda s: s["links"].append({"from": "src", "from_port": "Nope", "to": "blobs", "to_port": "Image"}), "link_port"),
    (lambda s: s["links"].append({"from": "src", "from_port": "Width", "to": "blur", "to_port": "Image"}), "type_mismatch"),
    (lambda s: s["links"].append({"from": "ghost", "from_port": "Image", "to": "blur", "to_port": "Image"}), "link_node"),
    (lambda s: s["links"].append({"from": "blur", "from_port": "Image", "to": "blur", "to_port": "Image"}), "self_link"),
])
def test_validation_catches_each_kind_of_mistake(mutate, code):
    spec = json.loads(json.dumps(GOOD))
    mutate(spec)
    assert code in codes(spec)
    assert spec_to_xml(spec)[0] == "", "an invalid spec must never produce XML"


def test_type_mismatch_and_cycles_are_reported_with_hints():
    spec = {"modules": [{"id": "src", "tool": "Image Source"}, {"id": "j", "tool": "Condition Branch"}],
            "links": [{"from": "src", "from_port": "Image", "to": "j", "to_port": "Val_In"}]}
    issues = validate_spec(spec)
    mismatch = next(i for i in issues if i["code"] == "type_mismatch")
    assert "IMAGE" in mismatch["message"] and "VALUE" in mismatch["message"] and mismatch["hint"]
    cyc = {"modules": [{"id": "a", "tool": "Image Filter"}, {"id": "b", "tool": "Image Filter"}],
           "links": [{"from": "a", "from_port": "Image", "to": "b", "to_port": "Image"},
                     {"from": "b", "from_port": "Image", "to": "a", "to_port": "Image"}]}
    assert "cycle" in codes(cyc)


def test_unknown_names_come_with_close_matches():
    spec = {"modules": [{"id": "a", "tool": "Image Filtr"}]}
    hint = next(i for i in validate_spec(spec) if i["code"] == "unknown_tool")["hint"]
    assert "Image Filter" in hint


def test_malformed_specs_do_not_crash():
    for bad in (None, [], "x", {}, {"modules": "no"}, {"modules": [1]}, {"modules": [{"id": "a b", "tool": "Histogram"}]},
                {"modules": [{"id": "a", "tool": "Histogram"}], "links": "x"}):
        assert has_errors(validate_spec(bad))


def test_side_effect_tools_are_flagged_and_warnings_do_not_block_building():
    spec = {"modules": [{"id": "src", "tool": "Image Source"}, {"id": "t", "tool": "TCP Send"}],
            "links": [{"from": "src", "from_port": "Width", "to": "t", "to_port": "Data"}]}
    issues = validate_spec(spec)
    assert any(i["code"] == "side_effects" for i in issues) and not has_errors(issues)
    assert build_flow(spec)[0] is not None


# ---------------------------------------------------------------- recipes and reference
RECIPES = reference_gen.load_recipes()


@pytest.mark.parametrize("name", sorted(RECIPES))
def test_every_recipe_validates_builds_and_runs(name):
    spec = RECIPES[name]["spec"]
    assert not has_errors(validate_spec(spec)), validate_spec(spec)
    xml, _ = spec_to_xml(spec)
    assert SolutionManager.from_xml(xml).flows
    result = api.dry_run(spec)
    assert result["ok"], result


def test_the_checked_in_reference_matches_the_engine():
    with open(reference_gen.REFERENCE, encoding="utf-8") as f:
        on_disk = f.read()
    assert on_disk == reference_gen.render(), "run: python scripts/gen_flow_reference.py"


def test_every_tool_and_recipe_has_its_own_retrievable_section():
    titles = {s["title"] for s in docs.sections()}
    assert {c["tool"] for c in catalog.full_catalog(builtin_only=True)} <= titles
    assert sum(t.startswith("Recipe:") for t in titles) == len(RECIPES)
    assert docs.read_section("caliper")["text"].startswith("*Category:*")
    assert docs.read_section("no-such-section") is None


def test_documentation_search_finds_the_relevant_pages():
    top = [h["title"] for h in docs.search_docs("two links into one input port rule")]
    assert "Common mistakes" in top or "How flows work" in top
    top = [h["title"] for h in docs.search_docs("check a colour covers enough of the image")]
    assert any("Colour" in t or "Color Extraction" in t for t in top)
    assert all(len(h["text"]) <= 2500 for h in docs.search_docs("caliper"))


# ---------------------------------------------------------------- api helpers
def test_dry_run_skips_side_effect_modules_and_reports_status():
    spec = {"modules": [{"id": "src", "tool": "Image Source"}, {"id": "t", "tool": "TCP Send", "params": {"mode": "TCP Client", "server_ip": "10.255.255.1"}}],
            "links": [{"from": "src", "from_port": "Width", "to": "t", "to_port": "Data"}]}
    res = api.dry_run(spec)
    assert res["skipped_side_effect_modules"] and res["modules"][0]["status"] == "OK"


def test_an_open_flow_can_be_read_back_as_a_valid_spec():
    from vm_clone.samples.pcb_solution import create_pcb_inspection_solution
    spec = api.pipeline_to_spec(create_pcb_inspection_solution())
    assert api.validate_flow(spec)["ok"] and len(spec["modules"]) == 7
    assert spec["modules"][1]["params"]["min_score"] == 0.70        # only non-default parameters are listed


# ---------------------------------------------------------------- the assistant loop (fake client)
class FakeStream:
    def __init__(self, blocks, stop):
        self._blocks, self._stop = blocks, stop
        self.text_stream = [b.text for b in blocks if b.type == "text"]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return SimpleNamespace(content=self._blocks, stop_reason=self._stop,
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def text(t):
    return SimpleNamespace(type="text", text=t)


def call(name, args, i=[0]):
    i[0] += 1
    return SimpleNamespace(type="tool_use", id=f"tu_{i[0]}", name=name, input=args)


class FakeClient:
    """Plays back scripted assistant turns and records what the agent sent."""

    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.messages = self

    def stream(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=lambda o: "<block>")))
        self.last = kw
        blocks = self.turns.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
        return FakeStream(blocks, stop)


def run(agent, prompt):
    events = []
    agent.run_turn(prompt, events.append)
    return events


def test_assistant_looks_up_docs_repairs_a_rejected_flow_and_proposes_it():
    bad = json.loads(json.dumps(GOOD))
    bad["modules"][1]["tool"] = "Gaussian Blur"                               # a hallucinated tool
    client = FakeClient([
        [text("Let me check the reference. "), call("search_docs", {"query": "count objects"})],
        [call("validate_flow", {"spec": bad})],
        [call("propose_flow", {"spec": bad, "summary": "first try"})],         # rejected: errors
        [call("get_tool_spec", {"tool": "Image Filter"}), call("propose_flow", {"spec": GOOD, "summary": "Blur, threshold, count."})],
        [text("Added a flow that blurs, binarises and counts blobs.")],
    ])
    agent = FlowAgent("sk-ant-test-key-0000000000000", client_factory=lambda k: client)
    events = run(agent, "count the blobs")
    kinds = [e["type"] for e in events]
    flows = [e for e in events if e["type"] == "flow"]
    assert len(flows) == 1 and flows[0]["spec"] == GOOD and flows[0]["xml"].startswith("<?xml")
    assert kinds[-1] == "done" and "error" not in kinds
    summaries = [e["summary"] for e in events if e["type"] == "tool"]
    assert any("Searched the reference" in s for s in summaries) and any("repairing" in s for s in summaries)
    # the model was told exactly what was wrong
    sent = json.dumps(client.requests[2]["messages"][-1], default=str)
    assert "unknown_tool" in sent and "Image Filter" in sent
    assert "".join(e["delta"] for e in events if e["type"] == "text").endswith("counts blobs.")
    assert agent.tokens["input"] == 500


def test_the_api_key_and_system_prompt_are_handled_safely():
    client = FakeClient([[text("hi")]])
    agent = FlowAgent("sk-ant-secret-key-000000000000", client_factory=lambda k: client)
    events = run(agent, "hello")
    sent = json.dumps(client.requests)
    assert "sk-ant-secret" not in sent and json.dumps(events).count("sk-ant-secret") == 0
    assert client.last["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert {t["name"] for t in client.last["tools"]} >= {"search_docs", "get_tool_spec", "validate_flow", "propose_flow", "dry_run"}
    assert "tool_choice" not in client.last and "thinking" not in client.last      # forced tool use / thinking config are rejected on current models
    assert all("input_schema" in t for t in _tool_defs())


def test_current_flow_tool_lets_the_model_modify_what_is_open():
    seen = {}
    client = FakeClient([[call("get_current_flow", {})], [text("ok")]])
    agent = FlowAgent("k", current_flow=lambda: GOOD, client_factory=lambda k: client)
    run(agent, "add a caliper to my flow")
    result = json.loads(client.requests[1]["messages"][-1]["content"][0]["content"])
    assert result["name"] == "Blur_Count"


@pytest.mark.parametrize("exc_name,expect", [("AuthenticationError", "API key was rejected"), ("RateLimitError", "Rate limit"),
                                              ("APIConnectionError", "internet"), ("NotFoundError", "model")])
def test_api_failures_become_actionable_messages(exc_name, expect):
    err = type(exc_name, (Exception,), {})("boom sk-ant-secret")

    class Boom:
        messages = None

        def __init__(self):
            self.messages = self

        def stream(self, **kw):
            raise err

    events = run(FlowAgent("k", client_factory=lambda k: Boom()), "hi")
    msg = next(e["message"] for e in events if e["type"] == "error")
    assert expect in msg and "sk-ant" not in msg
    assert events[-1]["type"] == "done"


def test_refusal_and_runaway_loops_end_cleanly():
    class Refusing(FakeClient):
        def stream(self, **kw):
            s = FakeStream([text("")], "refusal")
            return s

    ev = run(FlowAgent("k", client_factory=lambda k: Refusing([])), "x")
    assert any(e["type"] == "error" and "declined" in e["message"] for e in ev)

    loop = FakeClient([[call("search_tools", {"query": "x"})] for _ in range(30)])
    ev = run(FlowAgent("k", client_factory=lambda k: loop), "x")
    assert any(e["type"] == "notice" and "too many steps" in e["message"] for e in ev)


def test_cancelling_keeps_the_history_valid_for_the_next_turn():
    client = FakeClient([[call("search_tools", {"query": "x"})], [text("fine")]])
    agent = FlowAgent("k", client_factory=lambda k: client)
    agent.cancel = lambda: None
    agent._cancel.set()
    # simulate: cancel raised while the first response is being read
    orig = agent._loop

    def loop_then_cancel(emit):
        agent._cancel.clear()
        stream_cls = client.stream

        def stream(**kw):
            s = stream_cls(**kw)
            agent._cancel.set()
            return s
        client.stream = stream
        orig(emit)
        client.stream = stream_cls
    agent._loop = loop_then_cancel
    run(agent, "go")
    last = agent.messages[-1]
    assert last["role"] == "user" and last["content"][0]["type"] == "tool_result" and last["content"][0]["is_error"]
    agent._loop = orig
    agent._cancel.clear()
    run(agent, "again")                                           # the next turn continues without a protocol error
    assert agent.messages[-1]["role"] == "assistant"


def test_tool_errors_are_reported_to_the_model_not_raised():
    client = FakeClient([[call("get_tool_spec", {"tool": "Nope"})], [call("mystery", {})], [text("done")]])
    ev = run(FlowAgent("k", client_factory=lambda k: client), "x")
    assert not any(e["type"] == "error" for e in ev)
    results = [json.loads(m["content"]) for m in client.requests[2]["messages"][-1]["content"]]
    assert "Unknown tool" in results[0]["error"]
