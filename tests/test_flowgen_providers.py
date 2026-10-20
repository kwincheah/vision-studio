"""AI Gen providers: registry, key checks, model discovery, the OpenAI-style adapter (against a fake HTTP
transport), per-provider keys and persisted settings."""
import json
from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx")

from test_flowgen import GOOD
from vm_clone.flowgen import keystore, providers
from vm_clone.flowgen.agent import FlowAgent, SYSTEM_PROMPT, _tool_defs
from vm_clone.flowgen.openai_compat import OpenAICompatClient, to_openai_messages, to_openai_tools
from vm_clone.flowgen.settings import AISettings


# ---------------------------------------------------------------- registry
def test_all_major_providers_are_offered():
    ids = [p["id"] for p in providers.PROVIDERS]
    assert len(ids) == len(set(ids))
    assert {"anthropic", "openai", "gemini", "mistral", "deepseek", "xai", "groq", "openrouter", "ollama", "lmstudio", "custom"} <= set(ids)
    for p in providers.PROVIDERS:
        assert p["protocol"] in ("anthropic", "openai")
        assert p["id"] == "custom" or p["id"] == "lmstudio" or p["models"], p["id"]
        if p["protocol"] == "openai":
            assert p["base_url"] == "" or p["base_url"].startswith(("https://", "http://localhost"))
    assert not providers.get("ollama")["needs_key"] and providers.get("openai")["needs_key"]
    assert providers.get("no-such")["id"] == "anthropic"                       # unknown ids fall back safely


def test_public_list_contains_no_secrets_and_is_json_clean():
    data = providers.public_list()
    json.dumps(data)
    assert "env" not in data[0] and all("models" in d for d in data)


@pytest.mark.parametrize("provider,key,ok", [
    ("anthropic", "sk-ant-abcdefghijkl", True), ("anthropic", "abcdefghijkl", False), ("anthropic", "", False),
    ("openai", "sk-proj-abcdefghij", True), ("openai", "short", False), ("openai", "has space in it ok", False),
    ("gemini", "AIzaSyABCDEFGH", True), ("ollama", "", True), ("custom", "", True), ("groq", "gsk_abcdefgh", True), ("groq", "sk-abcdefgh", False)])
def test_key_checks_follow_each_providers_format(provider, key, ok):
    assert (providers.key_problem(provider, key) == "") is ok


def test_environment_keys_are_read_per_provider(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key-123456")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-123456")
    assert providers.env_key("gemini") == "g-key-123456" and providers.env_key("openai") == "sk-env-123456"
    assert providers.env_key("anthropic") == "" and providers.env_key("ollama") == ""


# ---------------------------------------------------------------- model discovery
def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_models_openai_style_sorts_and_strips_prefixes():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "models/gemini-2.5-pro"}, {"id": "gemini-2.0-flash"}, {"id": "gemini-2.0-flash"}]})
    ids = providers.fetch_models("gemini", "KEY123456", http_client=client_for(handler))
    assert ids == ["gemini-2.0-flash", "gemini-2.5-pro"]
    assert seen["url"].endswith("/v1beta/openai/models") and seen["auth"] == "Bearer KEY123456"


def test_fetch_models_for_claude_uses_the_anthropic_headers():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, json={"data": [{"id": "claude-opus-5-5"}, {"id": "claude-haiku-5-5"}]})
    assert providers.fetch_models("anthropic", "sk-ant-abcdefghij", http_client=client_for(handler)) == ["claude-haiku-5-5", "claude-opus-5-5"]
    assert seen["x-api-key"] == "sk-ant-abcdefghij" and seen["anthropic-version"]


def test_fetch_models_failures_are_readable():
    with pytest.raises(PermissionError):
        providers.fetch_models("openai", "sk-bad-12345", http_client=client_for(lambda r: httpx.Response(401, json={})))
    with pytest.raises(RuntimeError, match="500"):
        providers.fetch_models("openai", "sk-x-123456", http_client=client_for(lambda r: httpx.Response(500)))

    def refuse(req):
        raise httpx.ConnectError("refused")
    with pytest.raises(ConnectionError, match="localhost"):
        providers.fetch_models("ollama", "", http_client=client_for(refuse))
    with pytest.raises(ValueError):
        providers.fetch_models("custom", "", http_client=client_for(refuse))


def test_a_local_server_needs_no_key_header():
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"id": "llama3.1"}]})
    assert providers.fetch_models("ollama", "", http_client=client_for(handler)) == ["llama3.1"]
    assert seen["auth"] is None


# ---------------------------------------------------------------- message / tool conversion
def test_conversation_is_translated_to_chat_completions_shape():
    block = SimpleNamespace
    msgs = [
        {"role": "user", "content": "build it"},
        {"role": "assistant", "content": [block(type="text", text="Looking. "),
                                          block(type="tool_use", id="c1", name="search_docs", input={"query": "x"}),
                                          {"type": "tool_use", "id": "c2", "name": "get_tool_spec", "input": {"tool": "Caliper"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{\"a\":1}"},
                                     {"type": "tool_result", "tool_use_id": "c2", "content": "{\"b\":2}", "is_error": False}]},
    ]
    out = to_openai_messages([{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}], msgs)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "build it"}
    assert out[2]["role"] == "assistant" and out[2]["content"] == "Looking. "
    assert [c["id"] for c in out[2]["tool_calls"]] == ["c1", "c2"]
    assert json.loads(out[2]["tool_calls"][1]["function"]["arguments"]) == {"tool": "Caliper"}
    assert out[3:] == [{"role": "tool", "tool_call_id": "c1", "content": "{\"a\":1}"}, {"role": "tool", "tool_call_id": "c2", "content": "{\"b\":2}"}]


def test_tools_become_function_definitions():
    tools = to_openai_tools(_tool_defs())
    assert all(t["type"] == "function" and t["function"]["parameters"]["type"] == "object" for t in tools)
    assert {t["function"]["name"] for t in tools} >= {"propose_flow", "validate_flow"}


# ---------------------------------------------------------------- the adapter over fake HTTP
def sse(chunks):
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def chat_chunks(text=None, calls=None, finish="stop", usage=(12, 7)):
    out = []
    if text:
        for piece in (text[:len(text) // 2], text[len(text) // 2:]):
            out.append({"choices": [{"delta": {"content": piece}, "index": 0}]})
    for i, (cid, name, args) in enumerate(calls or []):
        half = len(args) // 2
        out.append({"choices": [{"delta": {"tool_calls": [{"index": i, "id": cid, "type": "function", "function": {"name": name, "arguments": args[:half]}}]}}]})
        out.append({"choices": [{"delta": {"tool_calls": [{"index": i, "function": {"arguments": args[half:]}}]}}]})
    out.append({"choices": [{"delta": {}, "finish_reason": "tool_calls" if calls else finish}]})
    out.append({"choices": [], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}})
    return out


def transport(responses, seen):
    def handler(req):
        seen.append((req.headers.get("authorization"), str(req.url), json.loads(req.content)))
        status, body = responses.pop(0)
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream" if status == 200 else "application/json"})
    return httpx.Client(transport=httpx.MockTransport(handler))


def run(agent, prompt):
    events = []
    agent.run_turn(prompt, events.append)
    return events


def test_streaming_text_tool_calls_and_usage_are_reassembled():
    seen = []
    args = json.dumps({"query": "caliper edges"})
    http = transport([(200, sse(chat_chunks(text="Hello there", calls=[("call_9", "search_tools", args)])))], seen)
    client = OpenAICompatClient("sk-test-123456", "https://api.example.com/v1/", http_client=http)
    with client.messages.stream(model="m1", system=[{"type": "text", "text": "S"}], tools=_tool_defs(), messages=[{"role": "user", "content": "hi"}]) as s:
        deltas = list(s.text_stream)
        final = s.get_final_message()
    assert "".join(deltas) == "Hello there"
    assert [b.type for b in final.content] == ["text", "tool_use"]
    assert final.content[1].name == "search_tools" and final.content[1].input == {"query": "caliper edges"} and final.content[1].id == "call_9"
    assert final.stop_reason == "tool_use" and final.usage.input_tokens == 12 and final.usage.output_tokens == 7
    auth, url, body = seen[0]
    assert auth == "Bearer sk-test-123456" and url == "https://api.example.com/v1/chat/completions"
    assert body["model"] == "m1" and body["stream"] is True and body["messages"][0]["role"] == "system"
    assert "cache_control" not in json.dumps(body) and "thinking" not in body and "tool_choice" not in body


@pytest.mark.parametrize("finish,stop", [("stop", "end_turn"), ("length", "max_tokens"), ("content_filter", "refusal")])
def test_finish_reasons_map_to_the_loops_stop_reasons(finish, stop):
    http = transport([(200, sse(chat_chunks(text="ab", finish=finish)))], [])
    client = OpenAICompatClient("", "http://localhost:11434/v1", http_client=http)
    with client.messages.stream(model="m", messages=[{"role": "user", "content": "x"}]) as s:
        assert s.get_final_message().stop_reason == stop


def test_without_a_key_no_authorization_header_is_sent():
    seen = []
    client = OpenAICompatClient("", "http://localhost:11434/v1", http_client=transport([(200, sse(chat_chunks(text="ok")))], seen))
    with client.messages.stream(model="llama3.1", messages=[{"role": "user", "content": "x"}]) as s:
        s.get_final_message()
    assert seen[0][0] is None


def test_tool_arguments_that_are_not_json_do_not_crash_the_loop():
    chunks = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "", "function": {"name": "search_tools", "arguments": "{oops"}}]}}]},
              {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
    client = OpenAICompatClient("k", "https://x/v1", http_client=transport([(200, sse(chunks))], []))
    with client.messages.stream(model="m", messages=[{"role": "user", "content": "x"}]) as s:
        final = s.get_final_message()
    assert final.content[0].input == {} and final.content[0].id == "call_0"          # an id is invented when the server sent none


def test_full_assistant_loop_runs_over_the_openai_style_protocol():
    seen = []
    script = [
        (200, sse(chat_chunks(text="Checking the reference.", calls=[("c1", "search_docs", json.dumps({"query": "count blobs"}))]))),
        (200, sse(chat_chunks(calls=[("c2", "propose_flow", json.dumps({"spec": GOOD, "summary": "Blob count."}))]))),
        (200, sse(chat_chunks(text="Done - the flow counts blobs."))),
    ]
    http = transport(script, seen)
    agent = FlowAgent("sk-openai-test-1234", model="gpt-4.1", client_factory=lambda k: OpenAICompatClient(k, "https://api.openai.com/v1", http_client=http))
    events = run(agent, "count the blobs")
    flow = next(e for e in events if e["type"] == "flow")
    assert flow["spec"]["name"] == "Blur_Count" and not any(e["type"] == "error" for e in events)
    assert "".join(e["delta"] for e in events if e["type"] == "text").endswith("counts blobs.")
    second = seen[1][2]["messages"]                                        # tool results go back as role=tool messages
    assert [m["role"] for m in second][-2:] == ["assistant", "tool"] and second[-1]["tool_call_id"] == "c1"
    assert second[-2]["tool_calls"][0]["function"]["name"] == "search_docs"
    assert seen[0][2]["messages"][0]["content"] == SYSTEM_PROMPT


@pytest.mark.parametrize("status,body,expect", [
    (401, {"error": {"message": "Incorrect API key provided"}}, "API key was rejected"),
    (404, {"error": {"message": "The model `gpt-9` does not exist"}}, "gpt-9"),
    (429, {"error": {"message": "You exceeded your current quota, please check your plan and billing details"}}, "out of credit"),
    (429, {"error": {"message": "Rate limit reached for requests"}}, "Rate limit"),
    (400, {"error": {"message": "tools are not supported for this model"}}, "tools are not supported"),
    (500, {"error": {"message": "upstream exploded"}}, "500"),
])
def test_http_errors_are_explained_without_leaking_the_key(status, body, expect):
    http = transport([(status, json.dumps(body).encode())], [])
    agent = FlowAgent("sk-secret-key-123456", model="m", client_factory=lambda k: OpenAICompatClient(k, "https://api.openai.com/v1", http_client=http))
    events = run(agent, "hi")
    msg = next(e["message"] for e in events if e["type"] == "error")
    assert expect in msg and "sk-secret" not in msg and events[-1]["type"] == "done"


def test_an_unreachable_server_is_reported_with_its_address():
    def refuse(req):
        raise httpx.ConnectError("refused")
    agent = FlowAgent("", model="llama3.1", client_factory=lambda k: OpenAICompatClient(k, "http://localhost:11434/v1", http_client=client_for(refuse)))
    msg = next(e["message"] for e in run(agent, "hi") if e["type"] == "error")
    assert "localhost:11434" in msg


# ---------------------------------------------------------------- persisted settings and keys
def test_settings_round_trip_and_survive_a_corrupt_file(tmp_path):
    path = str(tmp_path / "sub" / "ai.json")
    s = AISettings(path)
    assert s.provider == "anthropic" and not s.configured and s.model_for("openai") == "gpt-4.1"
    s.provider, s.configured = "openai", True
    s.models["openai"] = "gpt-4o"
    s.base_urls["custom"] = "http://10.0.0.5:8000/v1"
    s.save()
    again = AISettings(path)
    assert (again.provider, again.configured, again.model_for("openai"), again.base_url_for("custom")) == ("openai", True, "gpt-4o", "http://10.0.0.5:8000/v1")
    assert "sk-" not in open(path, encoding="utf-8").read()
    open(path, "w").write("{not json")
    assert AISettings(path).provider == "anthropic"
    open(path, "w").write(json.dumps({"provider": "bogus", "models": [1], "base_urls": "x"}))
    assert AISettings(path).provider == "anthropic"


def test_keys_are_stored_per_provider_and_removed_independently(monkeypatch):
    vault = {}
    fake = SimpleNamespace(set_password=lambda s, a, k: vault.__setitem__((s, a), k), get_password=lambda s, a: vault.get((s, a)),
                           delete_password=lambda s, a: vault.pop((s, a), None), get_keyring=lambda: SimpleNamespace())
    monkeypatch.setattr(keystore, "_keyring", lambda: fake)
    assert keystore.save("openai", "sk-openai-1234567") and keystore.save("anthropic", "sk-ant-abcdefghij")
    assert keystore.load_saved("openai") == "sk-openai-1234567" and keystore.load_saved("anthropic") == "sk-ant-abcdefghij"
    assert keystore.load_saved("gemini") == ""
    keystore.forget("openai")
    assert keystore.load_saved("openai") == "" and keystore.load_saved("anthropic")
    assert keystore.mask("sk-openai-1234567") == "sk-open...4567"


def test_fetched_lists_keep_only_chat_models_for_hosted_providers_and_everything_for_local_ones():
    data = {"data": [{"id": "gpt-4.1"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "dall-e-3"},
                     {"id": "gpt-4o-mini-tts"}, {"id": "omni-moderation-latest"}, {"id": "o4-mini"}]}
    client = client_for(lambda r: httpx.Response(200, json=data))
    assert providers.fetch_models("openai", "sk-abcdefgh", http_client=client) == ["gpt-4.1", "o4-mini"]
    assert len(providers.fetch_models("ollama", "", http_client=client)) == 7
    assert len(providers.fetch_models("openai", "sk-abcdefgh", http_client=client, chat_only=False)) == 7
