"""The AI flow assistant: a tool-using Claude conversation that reads the reference and proposes flows.

The model does not write XML.  It looks things up (``search_tools`` / ``get_tool_spec`` / ``search_docs`` /
``read_doc``), drafts a spec, gets precise problems back from ``validate_flow`` and repairs them, then
hands the finished spec to ``propose_flow``.  The application turns the spec into a flow with its own
serialiser and shows it to the user, who decides whether to add it.

``FlowAgent.run_turn`` blocks (call it from a worker thread) and reports progress through ``emit``.
"""
import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from vm_clone.core.registry import list_all_tools
from vm_clone.flowgen import api
from vm_clone.flowgen.catalog import SIDE_EFFECT_TOOLS
from vm_clone.flowgen.spec import SPEC_SCHEMA, has_errors, spec_to_xml, validate_spec

logger = logging.getLogger("vm_clone.flowgen")

MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5 (most capable)"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5 (balanced)"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5 (fastest, cheapest)"},
]
DEFAULT_MODEL = MODELS[1]["id"]
MAX_STEPS = 14

SYSTEM_PROMPT = """You are the flow assistant built into Apex Industrial Vision Studio, a machine-vision application where users build inspection flows from modules (tools) connected by links.

Your job: turn the user's request into a working flow, or answer questions about building flows.

How to work:
1. Look things up instead of guessing. Use search_docs / read_doc for concepts and worked recipes, search_tools to find tools, and get_tool_spec for the exact ports and parameters of every tool you use. Tool names, port names and parameter names must be copied exactly.
2. Draft a flow spec, call validate_flow, and fix every error it reports (read its hints). Repeat until it is clean. Use dry_run when the user wants to know that the flow actually runs.
3. When the spec is valid, call propose_flow once with a short summary. The application builds the flow and shows it to the user, who chooses whether to add it. You never write XML yourself.
4. If the user asks to change the flow that is already open, call get_current_flow first and propose the complete modified flow.

Rules:
- Use only tools that exist. Set only the parameters the task needs; keep defaults otherwise.
- Do not add modules the user did not ask for. Keep flows as small as the task allows.
- Modules with side effects (TCP Send, Script, Image Output, Camera IO) only when asked, and say so in your reply so the user can review their settings.
- If a request is too vague to build anything sensible, ask one short question. Otherwise state the assumptions you made (image size, thresholds, regions) in one or two lines.
- Reply briefly in plain language: what the flow does, which modules, and what to adjust. No XML, no long JSON in the reply."""


def _tool_defs() -> List[Dict[str, Any]]:
    spec_arg = {"spec": dict(SPEC_SCHEMA, description="The flow specification")}
    return [
        {"name": "search_tools", "description": "Keyword search over the installed vision tools (name, category, description, ports, parameters).",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "category": {"type": "string", "description": "optional exact category"}}, "required": ["query"]}},
        {"name": "get_tool_spec", "description": "Exact input ports, output ports (with types) and parameters (defaults, allowed values) of one tool.",
         "input_schema": {"type": "object", "properties": {"tool": {"type": "string"}}, "required": ["tool"]}},
        {"name": "search_docs", "description": "Search the flow-building reference (concepts, port-type rules, worked recipes, per-tool pages). Returns the best sections.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
        {"name": "read_doc", "description": "Read one reference section by id or title (ids come from search_docs).",
         "input_schema": {"type": "object", "properties": {"section": {"type": "string"}}, "required": ["section"]}},
        {"name": "get_current_flow", "description": "The flow currently open on the user's canvas, as a spec.",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "validate_flow", "description": "Check a spec: unknown tools/ports/parameters, type mismatches, taken inputs, cycles. Returns issues with hints.",
         "input_schema": {"type": "object", "properties": spec_arg, "required": ["spec"]}},
        {"name": "dry_run", "description": "Run a valid spec once on synthetic input and report each module's status. Side-effect modules are skipped.",
         "input_schema": {"type": "object", "properties": spec_arg, "required": ["spec"]}},
        {"name": "propose_flow", "description": "Hand the finished, valid spec to the application, which shows it to the user. Call once when the flow is ready.",
         "input_schema": {"type": "object", "properties": dict(spec_arg, summary={"type": "string", "description": "One or two sentences: what the flow does"}), "required": ["spec", "summary"]}},
    ]


def _block_get(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


class FlowAgent:
    """One conversation.  ``client_factory`` returns an Anthropic-compatible client (tests inject a fake)."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, current_flow: Optional[Callable[[], Dict[str, Any]]] = None,
                 client_factory: Optional[Callable[[str], Any]] = None):
        self.api_key = api_key
        self.model = model
        self.current_flow = current_flow
        self._client_factory = client_factory or self._default_client
        self._client = None
        self.messages: List[Dict[str, Any]] = []
        self._cancel = threading.Event()
        self.tokens = {"input": 0, "output": 0}

    @staticmethod
    def _default_client(api_key: str):
        import anthropic
        return anthropic.Anthropic(api_key=api_key, max_retries=2)

    def cancel(self) -> None:
        self._cancel.set()

    def reset(self) -> None:
        self.messages = []

    # ------------------------------------------------------------------ tool execution
    def _run_tool(self, name: str, args: Dict[str, Any], emit) -> Dict[str, Any]:
        try:
            if name == "search_tools":
                return api.search_tools(args.get("query", ""), args.get("category", ""))
            if name == "get_tool_spec":
                return api.get_tool_spec(args.get("tool", ""))
            if name == "search_docs":
                return api.search_docs(args.get("query", ""))
            if name == "read_doc":
                return api.read_doc(args.get("section", ""))
            if name == "get_current_flow":
                return self.current_flow() if self.current_flow else {"error": "No flow is open."}
            if name == "validate_flow":
                return api.validate_flow(args.get("spec"))
            if name == "dry_run":
                return api.dry_run(args.get("spec"))
            if name == "propose_flow":
                spec = args.get("spec")
                issues = validate_spec(spec)
                if has_errors(issues):
                    return {"accepted": False, "issues": issues, "message": "Fix these errors and call propose_flow again."}
                xml, _ = spec_to_xml(spec)
                emit({"type": "flow", "spec": spec, "xml": xml, "summary": str(args.get("summary", "")), "issues": issues,
                      "side_effects": sorted({m["tool"] for m in spec["modules"] if m["tool"] in SIDE_EFFECT_TOOLS})})
                return {"accepted": True, "message": "The flow was shown to the user. Finish with a short reply.", "warnings": issues}
            return {"error": f"Unknown tool {name!r}."}
        except Exception as exc:                   # a tool bug is reported to the model, never crashes the chat
            logger.exception("assistant tool %s failed", name)
            return {"error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _summary(name: str, args: Dict[str, Any], result: Dict[str, Any]) -> str:
        if name == "search_tools":
            return f"Searched tools for '{args.get('query', '')}' ({len(result.get('tools', []))} found)"
        if name == "get_tool_spec":
            return f"Read the spec of {args.get('tool', '')}"
        if name == "search_docs":
            return f"Searched the reference for '{args.get('query', '')}'"
        if name == "read_doc":
            return f"Read reference section '{result.get('title', args.get('section', ''))}'"
        if name == "get_current_flow":
            return "Read the open flow"
        if name == "validate_flow":
            n = sum(1 for i in result.get("issues", []) if i["severity"] == "error")
            return "Validated the flow: no errors" if result.get("ok") else f"Validated the flow: {n} error(s) to fix"
        if name == "dry_run":
            return "Test-ran the flow" if result.get("ok") else "Test run found problems"
        if name == "propose_flow":
            return "Built the flow" if result.get("accepted") else "Flow rejected - repairing"
        return name

    # ------------------------------------------------------------------ one user turn
    def run_turn(self, text: str, emit: Callable[[Dict[str, Any]], None]) -> None:
        self._cancel.clear()
        self.messages.append({"role": "user", "content": text})
        try:
            if self._client is None:
                self._client = self._client_factory(self.api_key)
            self._loop(emit)
        except Exception as exc:
            emit({"type": "error", "message": self._explain(exc)})
        finally:
            emit({"type": "done", "tokens": dict(self.tokens)})

    def _loop(self, emit) -> None:
        for _step in range(MAX_STEPS):
            if self._cancel.is_set():
                emit({"type": "notice", "message": "Stopped."})
                return
            with self._client.messages.stream(
                model=self.model, max_tokens=16000,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                tools=_tool_defs(), messages=self.messages,
            ) as stream:
                for chunk in stream.text_stream:
                    if self._cancel.is_set():
                        break
                    emit({"type": "text", "delta": chunk})
                final = stream.get_final_message()
            usage = getattr(final, "usage", None)
            if usage is not None:
                self.tokens["input"] += getattr(usage, "input_tokens", 0) or 0
                self.tokens["output"] += getattr(usage, "output_tokens", 0) or 0
            self.messages.append({"role": "assistant", "content": final.content})
            stop = getattr(final, "stop_reason", "end_turn")
            if stop == "refusal":
                emit({"type": "error", "message": "The model declined this request. Try rephrasing it."})
                return
            if stop == "max_tokens":
                emit({"type": "notice", "message": "The reply was cut off (length limit). Ask me to continue."})
                return
            calls = [b for b in final.content if _block_get(b, "type") == "tool_use"]
            if stop != "tool_use" or not calls:
                return
            if self._cancel.is_set():                  # keep the history valid: every tool_use needs a result
                self.messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": _block_get(c, "id"), "content": "Cancelled by the user.", "is_error": True}
                    for c in calls]})
                emit({"type": "notice", "message": "Stopped."})
                return
            results = []
            for call in calls:
                args = _block_get(call, "input") or {}
                result = self._run_tool(_block_get(call, "name"), args, emit)
                emit({"type": "tool", "name": _block_get(call, "name"), "summary": self._summary(_block_get(call, "name"), args, result),
                      "ok": not result.get("error") and result.get("ok", True) is not False})
                results.append({"type": "tool_result", "tool_use_id": _block_get(call, "id"),
                                "content": json.dumps(result, default=str)[:40000],
                                "is_error": bool(result.get("error"))})
            self.messages.append({"role": "user", "content": results})
        emit({"type": "notice", "message": "I stopped after too many steps. Tell me what to adjust and I will continue."})

    @staticmethod
    def _explain(exc: Exception) -> str:
        """A message a user can act on, without leaking the key."""
        name = type(exc).__name__
        if getattr(exc, "user_message", ""):                 # providers behind the OpenAI-style adapter explain themselves
            return exc.user_message
        if name == "AuthenticationError":
            return "The API key was rejected. Check it in AI Gen settings."
        if name == "PermissionDeniedError":
            return "This API key is not allowed to use the selected model."
        if name == "RateLimitError":
            return "Rate limit reached. Wait a moment and try again."
        if name == "NotFoundError":
            return "The selected model is not available for this key. Choose another model in the AI Gen settings."
        if name in ("APIConnectionError", "APITimeoutError"):
            return "Could not reach the AI provider. Check the internet connection."
        if name == "BadRequestError":
            return f"The request was rejected: {str(exc)[:300]}"
        if name == "ModuleNotFoundError":
            return "The 'anthropic' package is not installed (pip install anthropic)."
        return f"{name}: {str(exc)[:300]}"
