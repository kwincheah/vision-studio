"""The assistant against the real Anthropic SDK (client code, streaming parser, request serialisation) with a
fake HTTP transport instead of the network - proves the wire format, not just our own fake client."""
import json
import os

import pytest

anthropic = pytest.importorskip("anthropic")
httpx = pytest.importorskip("httpx")

from test_flowgen import GOOD
from apex_vision.flowgen.agent import FlowAgent


def sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def message(blocks, stop):
    """Server-sent events for one assistant message made of ('text', str) / ('tool', id, name, input) blocks."""
    ev = [{"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                                                "content": [], "stop_reason": None, "stop_sequence": None,
                                                "usage": {"input_tokens": 11, "output_tokens": 1}}}]
    for i, b in enumerate(blocks):
        if b[0] == "text":
            ev += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                   {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b[1]}}]
        else:
            ev += [{"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": b[1], "name": b[2], "input": {}}},
                   {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(b[3])}}]
        ev.append({"type": "content_block_stop", "index": i})
    ev += [{"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 9}},
           {"type": "message_stop"}]
    return sse(ev)


def make_client(script, seen):
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((request.headers.get("x-api-key"), body))
        status, payload = script.pop(0)
        return httpx.Response(status, content=payload, headers={"content-type": "text/event-stream" if status == 200 else "application/json"})
    return lambda key: anthropic.Anthropic(api_key=key, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def run(agent, prompt):
    events = []
    agent.run_turn(prompt, events.append)
    return events


def test_full_tool_loop_over_the_real_sdk_streaming_parser():
    seen = []
    script = [
        (200, message([("text", "Looking it up. "), ("tool", "toolu_1", "search_tools", {"query": "caliper"})], "tool_use")),
        (200, message([("tool", "toolu_2", "propose_flow", {"spec": GOOD, "summary": "Blob count."})], "tool_use")),
        (200, message([("text", "Done - flow added.")], "end_turn")),
    ]
    agent = FlowAgent("sk-ant-wire-test-0000000000000", model="claude-sonnet-5-5", client_factory=make_client(script, seen))
    events = run(agent, "count blobs")
    assert [e["type"] for e in events][-1] == "done" and not any(e["type"] == "error" for e in events)
    flow = next(e for e in events if e["type"] == "flow")
    assert flow["spec"]["name"] == "Blur_Count" and flow["xml"].startswith("<?xml")
    assert "".join(e["delta"] for e in events if e["type"] == "text") == "Looking it up. Done - flow added."

    key, first = seen[0]
    assert key == "sk-ant-wire-test-0000000000000"
    assert first["model"] == "claude-sonnet-5-5" and first["stream"] is True and first["max_tokens"] == 16000
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in first and "thinking" not in first and "temperature" not in first
    assert {t["name"] for t in first["tools"]} >= {"search_tools", "get_tool_spec", "search_docs", "read_doc", "validate_flow", "propose_flow"}
    assert first["messages"] == [{"role": "user", "content": "count blobs"}]

    # the second request carries the assistant's tool_use and our tool_result back, in valid shape
    second = seen[1][1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert any(b["type"] == "tool_use" and b["id"] == "toolu_1" for b in second[1]["content"])
    result = second[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1" and "Caliper" in result["content"]
    assert agent.tokens["input"] == 33 and agent.tokens["output"] == 27


def test_http_errors_map_to_user_messages_and_never_include_the_key():
    err = json.dumps({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}).encode()
    seen = []
    agent = FlowAgent("sk-ant-bad-0000000000000000", client_factory=make_client([(401, err)], seen))
    events = run(agent, "hi")
    msg = next(e["message"] for e in events if e["type"] == "error")
    assert "API key was rejected" in msg and "sk-ant" not in msg

    rate = json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}).encode()
    agent = FlowAgent("sk-ant-x-0000000000000000", client_factory=make_client([(429, rate)], []))
    assert "Rate limit" in next(e["message"] for e in run(agent, "hi") if e["type"] == "error")

    nf = json.dumps({"type": "error", "error": {"type": "not_found_error", "message": "model: nope"}}).encode()
    agent = FlowAgent("sk-ant-x-0000000000000000", model="nope", client_factory=make_client([(404, nf)], []))
    assert "model" in next(e["message"] for e in run(agent, "hi") if e["type"] == "error")


@pytest.mark.skipif(not os.environ.get("APEX_LIVE_AI_TEST") or not os.environ.get("ANTHROPIC_API_KEY"),
                    reason="live check: set APEX_LIVE_AI_TEST=1 and ANTHROPIC_API_KEY (spends a few cents)")
def test_live_prompt_to_valid_flow():
    agent = FlowAgent(os.environ["ANTHROPIC_API_KEY"], model="claude-haiku-5-5")
    events = run(agent, "Measure the width between two edges and pass if it is between 100 and 300 pixels.")
    flows = [e for e in events if e["type"] == "flow"]
    assert flows and not any(e["type"] == "error" for e in events), events
    from apex_vision.flowgen.api import dry_run
    assert dry_run(flows[-1]["spec"])["ok"]
