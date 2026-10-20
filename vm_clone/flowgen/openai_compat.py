"""OpenAI-style Chat Completions client that looks like the Anthropic SDK to the assistant loop.

``FlowAgent`` speaks the Anthropic request/response shape (system blocks, ``tools`` with ``input_schema``,
assistant ``tool_use`` / user ``tool_result`` blocks, ``client.messages.stream``).  This adapter translates that
to ``POST {base_url}/chat/completions`` (streaming) and builds an Anthropic-shaped final message back, so the
same loop drives OpenAI, Gemini, Mistral, DeepSeek, xAI, Groq, OpenRouter, Ollama, LM Studio and custom servers.
"""
import json
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional


class ProviderError(Exception):
    """Base class; subclasses are named like the Anthropic SDK's so the assistant explains them uniformly."""
    user_message = ""


class AuthenticationError(ProviderError):
    pass


class PermissionDeniedError(ProviderError):
    pass


class RateLimitError(ProviderError):
    pass


class NotFoundError(ProviderError):
    pass


class BadRequestError(ProviderError):
    pass


class APIConnectionError(ProviderError):
    pass


def _get(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def to_openai_messages(system: Any, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Anthropic-shaped conversation -> Chat Completions messages."""
    out: List[Dict[str, Any]] = []
    if system:
        text = system if isinstance(system, str) else "\n\n".join(_get(b, "text", "") for b in system)
        out.append({"role": "system", "content": text})
    for m in messages:
        content = m["content"]
        if m["role"] == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            texts = []
            for b in content:
                if _get(b, "type") == "tool_result":
                    out.append({"role": "tool", "tool_call_id": _get(b, "tool_use_id"), "content": str(_get(b, "content", ""))})
                elif _get(b, "type") == "text":
                    texts.append(_get(b, "text", ""))
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
        else:
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
                continue
            text = "".join(_get(b, "text", "") for b in content if _get(b, "type") == "text")
            calls = [{"id": _get(b, "id"), "type": "function",
                      "function": {"name": _get(b, "name"), "arguments": json.dumps(_get(b, "input") or {})}}
                     for b in content if _get(b, "type") == "tool_use"]
            msg: Dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    return out


def to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("input_schema", {"type": "object", "properties": {}})}} for t in tools]


_FINISH = {"stop": "end_turn", "tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens",
           "content_filter": "refusal"}


class _Stream:
    def __init__(self, client: "OpenAICompatClient", payload: Dict[str, Any]):
        self._client, self._payload = client, payload
        self._text: List[str] = []
        self._calls: Dict[int, Dict[str, str]] = {}
        self._finish: Optional[str] = None
        self._usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        self._consumed = False
        self.text_stream = self._iterate()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _iterate(self) -> Iterator[str]:
        for chunk in self._client._post_stream(self._payload):
            usage = chunk.get("usage")
            if usage:
                self._usage = SimpleNamespace(input_tokens=usage.get("prompt_tokens", 0) or 0,
                                              output_tokens=usage.get("completion_tokens", 0) or 0)
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    self._text.append(piece)
                    yield piece
                for tc in delta.get("tool_calls") or []:
                    slot = self._calls.setdefault(tc.get("index", len(self._calls)), {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["name"] = fn.get("name") or slot["name"]
                    args = fn.get("arguments")
                    slot["args"] += args if isinstance(args, str) else (json.dumps(args) if args else "")
                if choice.get("finish_reason"):
                    self._finish = choice["finish_reason"]
        self._consumed = True

    def get_final_message(self):
        if not self._consumed:
            for _ in self.text_stream:                     # nothing read the text yet: drain it
                pass
        blocks: List[Any] = []
        text = "".join(self._text)
        if text:
            blocks.append(SimpleNamespace(type="text", text=text))
        for i, slot in sorted(self._calls.items()):
            try:
                args = json.loads(slot["args"]) if slot["args"].strip() else {}
            except ValueError:
                args = {}
            blocks.append(SimpleNamespace(type="tool_use", id=slot["id"] or f"call_{i}", name=slot["name"], input=args))
        stop = "tool_use" if self._calls else _FINISH.get(self._finish or "stop", "end_turn")
        return SimpleNamespace(content=blocks, stop_reason=stop, usage=self._usage)


class OpenAICompatClient:
    """``client.messages.stream(model=..., system=..., tools=..., messages=...)`` over Chat Completions."""

    def __init__(self, api_key: str, base_url: str, http_client: Any = None, timeout: float = 120.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = http_client
        self._timeout = timeout
        self.messages = self

    def stream(self, *, model: str, messages: List[Dict[str, Any]], system: Any = None, tools: Any = None, **_ignored) -> _Stream:
        payload: Dict[str, Any] = {"model": model, "messages": to_openai_messages(system, messages), "stream": True,
                                   "stream_options": {"include_usage": True}}
        if tools:
            payload["tools"] = to_openai_tools(tools)
        return _Stream(self, payload)

    # ---- transport
    def _post_stream(self, payload: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        import httpx
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        client = self._http or httpx.Client(timeout=self._timeout)
        try:
            with client.stream("POST", self.base_url + "/chat/completions", headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", "replace")
                    raise self._error(resp.status_code, body)
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except ValueError:
                        continue
        except httpx.TransportError as exc:
            err = APIConnectionError(f"Could not reach {self.base_url}")
            err.user_message = f"Could not reach {self.base_url}. Check the address and your connection."
            raise err from None

    @staticmethod
    def _error(status: int, body: str) -> ProviderError:
        detail = ""
        try:
            data = json.loads(body)
            err = data.get("error", data)
            detail = (err.get("message") if isinstance(err, dict) else str(err)) or ""
        except ValueError:
            detail = body[:200]
        detail = detail.strip()[:300]
        if status in (401, 403) and ("key" in detail.lower() or status == 401 or not detail):
            cls, msg = AuthenticationError, "The API key was rejected. Check it in the AI Gen settings."
        elif status == 403:
            cls, msg = PermissionDeniedError, "This key is not allowed to use that model."
        elif status == 404:
            cls, msg = NotFoundError, f"The model or address was not found. {detail}".strip()
        elif status == 429:
            quota = "quota" in detail.lower() or "billing" in detail.lower()
            cls, msg = RateLimitError, ("The account is out of credit or over its quota. " if quota else "Rate limit reached. Wait a moment and try again. ") + detail
        elif status in (400, 422):
            cls, msg = BadRequestError, f"The provider rejected the request: {detail}"
        else:
            cls, msg = ProviderError, f"The provider answered {status}. {detail}"
        err = cls(f"{status} {detail}")
        err.user_message = msg.strip()
        return err
