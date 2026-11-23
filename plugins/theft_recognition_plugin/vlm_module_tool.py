"""Generic domain-agnostic VLM API plugin tool."""
from __future__ import annotations

import base64
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import copy
import json
import os
import re
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

from apex_vision.core.base_tool import DataType, ToolExecutionResult, ToolPort, ToolStatus
from apex_vision.sdk import ParamDef, ParamType, PluginToolBase

_PROVIDER_CONFIG: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "openai": ("https://api.openai.com/v1", ("VLM_API_KEY", "OPENAI_API_KEY")),
    "deepseek": ("https://api.deepseek.com", ("VLM_API_KEY", "DEEPSEEK_API_KEY")),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", ("VLM_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")),
    "anthropic": ("https://api.anthropic.com", ("VLM_API_KEY", "ANTHROPIC_API_KEY")),
    "openrouter": ("https://openrouter.ai/api/v1", ("VLM_API_KEY", "OPENROUTER_API_KEY")),
    "ollama": ("http://127.0.0.1:11434/v1", ()),
    "lmstudio": ("http://127.0.0.1:1234/v1", ()),
    "custom": ("", ("VLM_API_KEY", "OPENAI_API_KEY")),
}


def resolve_endpoint_and_key(provider: str, base_url_override: str, api_key_override: str) -> Tuple[str, str, str]:
    """Resolve provider, base URL, and API key from params, env vars, or keystore."""
    prov = (provider or "openai").strip().lower()
    default_url, env_names = _PROVIDER_CONFIG.get(prov, _PROVIDER_CONFIG["custom"])
    base_url = (base_url_override or "").strip() or os.environ.get("VLM_BASE_URL", "").strip() or default_url

    key = (api_key_override or "").strip()
    if not key:
        for env_k in env_names:
            val = os.environ.get(env_k, "").strip()
            if val:
                key = val
                break
    if not key and prov in ("openai", "deepseek", "gemini", "anthropic", "openrouter"):
        try:
            from apex_vision.flowgen import keystore
            saved = keystore.load_saved(prov)
            if saved:
                key = saved.strip()
        except Exception:
            pass
    return prov, base_url, key


def parse_json_response(text: str) -> Dict[str, Any]:
    """Extract a JSON object from raw or markdown-fenced VLM output."""
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    else:
        brace = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace:
            raw = brace.group(0).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _parse_rate_limit_details(resp: Any) -> Tuple[float, bool, str]:
    wait_sec = 0.0
    headers = getattr(resp, "headers", None)
    if headers is not None and hasattr(headers, "get"):
        ra_raw = headers.get("Retry-After") or headers.get("retry-after") or ""
        try:
            if ra_raw:
                wait_sec = max(0.0, float(str(ra_raw).strip()))
        except Exception:
            wait_sec = 0.0

    raw_text = ""
    try:
        j = resp.json()
        if isinstance(j, (dict, list)):
            raw_text = json.dumps(j)
    except Exception:
        pass
    if not raw_text:
        try:
            raw_text = str(getattr(resp, "text", "") or "")
        except Exception:
            raw_text = ""

    if wait_sec <= 0.0 and raw_text:
        for pat in (
            r"retryDelay[\"'\s:=]+([0-9]+(?:\.[0-9]+)?)s?",
            r"retry in\s+([0-9]+(?:\.[0-9]+)?)\s*s",
        ):
            m = re.search(pat, raw_text, re.IGNORECASE)
            if m:
                try:
                    wait_sec = max(0.0, float(m.group(1)))
                    break
                except Exception:
                    pass

    lower = raw_text.lower()
    is_daily = any(k in lower for k in ("perday", "requestsperday", "per_day", "requests per day"))
    if wait_sec <= 0.0:
        wait_sec = 60.0 if is_daily else 15.0
    detail = raw_text.strip()[:220] or "HTTP 429 Too Many Requests"
    return wait_sec, is_daily, detail


def _extract_http_error_detail(resp: Any) -> str:
    try:
        j = resp.json()
        if isinstance(j, dict):
            err = j.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])[:260]
            if j.get("message"):
                return str(j["message"])[:260]
            return json.dumps(j)[:260]
    except Exception:
        pass
    try:
        txt = str(getattr(resp, "text", "") or "").strip()
        return txt[:260] if txt else ""
    except Exception:
        return ""


def _post_with_400_fallback(
    requests_mod,
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout_sec: float,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
):
    rate_retried = False
    while True:
        resp = requests_mod.post(url, headers=headers, json=payload, timeout=timeout_sec)
        status = int(getattr(resp, "status_code", 200) or 200)
        if status == 400:
            err_detail = _extract_http_error_detail(resp)
            low = err_detail.lower()
            if "max_completion_tokens" in low and "max_tokens" in payload:
                payload["max_completion_tokens"] = payload.pop("max_tokens")
                continue
            if "temperature" in low and "temperature" in payload:
                payload.pop("temperature", None)
                continue
            if "response_format" in payload:
                payload.pop("response_format", None)
                continue
            if "reasoning_effort" in payload:
                payload.pop("reasoning_effort", None)
                continue
            if err_detail:
                raise RuntimeError(f"HTTP 400 for {url}: {err_detail}")
        if status in (429, 503):
            wait_sec, is_daily, detail = _parse_rate_limit_details(resp)
            if not rate_retried and not is_daily and wait_sec <= 15.0:
                rate_retried = True
                if wait_sec > 0.0:
                    sleep_fn(wait_sec)
                continue
            if is_daily:
                raise RuntimeError(
                    f"HTTP {status} Gemini daily free-tier RPD quota exhausted "
                    f"(enable billing or switch model/provider): {detail}"
                )
            raise RuntimeError(f"HTTP {status} Rate limit exceeded (cooldown {max(15.0, min(60.0, wait_sec)):.0f}s): {detail}")
        if status >= 400:
            err_detail = _extract_http_error_detail(resp)
            if err_detail:
                raise RuntimeError(f"HTTP {status} for {url}: {err_detail}")
        resp.raise_for_status()
        return resp


def _extract_choice_text(choice: Dict[str, Any]) -> Tuple[str, str]:
    msg_content = choice["message"]["content"]
    if isinstance(msg_content, list):
        text = "\n".join(part.get("text", "") for part in msg_content if isinstance(part, dict))
    else:
        text = str(msg_content)
    finish_reason = str(choice.get("finish_reason") or "").strip().lower()
    return text, finish_reason


def _encode_image_b64(img: np.ndarray) -> str:
    if img is None or not isinstance(img, np.ndarray) or img.size == 0:
        return ""
    work = img
    if work.dtype != np.uint8:
        work = np.clip(work, 0, 255).astype(np.uint8)
    if work.ndim == 3:
        c = work.shape[2]
        if c == 1:
            work = work[:, :, 0]
        elif c == 2:
            work = np.dstack([work[:, :, 0], work[:, :, 1], work[:, :, 0]])
        elif c == 4:
            work = cv2.cvtColor(work, cv2.COLOR_BGRA2BGR)
        elif c > 3:
            work = np.ascontiguousarray(work[:, :, :3])
    ok, buf = cv2.imencode(".jpg", work, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def _encode_frames_b64(frames_raw: Any, max_frames: int = 16) -> List[str]:
    if not isinstance(frames_raw, (list, tuple)) or not frames_raw:
        return []
    out: List[str] = []
    for item in frames_raw:
        if len(out) >= max_frames:
            break
        if isinstance(item, (bytes, bytearray)):
            if item:
                out.append(base64.b64encode(bytes(item)).decode("ascii"))
        elif isinstance(item, str):
            s = item.strip()
            if s.startswith("data:image/") and "," in s:
                s = s.split(",", 1)[1].strip()
            if s:
                out.append(s)
        elif isinstance(item, np.ndarray) and item.size > 0:
            enc = _encode_image_b64(item)
            if enc:
                out.append(enc)
    return out


def call_generic_vlm(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model_name: str,
    prompt: str,
    system_prompt: str,
    image_b64: str,
    temperature: float,
    max_tokens: int,
    timeout_sec: float,
    frames_b64: Optional[List[str]] = None,
    want_json: bool = False,
) -> str:
    """Call OpenAI-compatible or Anthropic VLM endpoint with arbitrary prompt and image(s)."""
    import requests

    images_b64 = [b for b in (frames_b64 or []) if b]
    if not images_b64 and image_b64:
        images_b64 = [image_b64]

    if provider == "anthropic":
        url = base_url.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        content: Any = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}
            for b64 in images_b64
        ]
        content.append({"type": "text", "text": prompt})
        payload: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        resp = _post_with_400_fallback(requests, url, headers, payload, timeout_sec)
        blocks = resp.json().get("content") or []
        return "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict))

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    user_content: Any = [{"type": "text", "text": prompt}]
    for b64 in images_b64:
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    prov_l = (provider or "").strip().lower()
    model_l = (model_name or "").strip().lower()
    is_gemini = prov_l == "gemini" or "gemini" in model_l
    supports_reasoning_effort = is_gemini and any(v in model_l for v in ("2.5", "3", "4"))
    req_tokens = int(max_tokens or 2048)
    effective_max_tokens = max(req_tokens, 2048) if is_gemini else max(256, req_tokens)

    payload: Dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "max_tokens": effective_max_tokens,
        "messages": messages,
    }
    if want_json:
        payload["response_format"] = {"type": "json_object"}
    if supports_reasoning_effort:
        payload["reasoning_effort"] = "low"

    resp = _post_with_400_fallback(requests, url, headers, payload, timeout_sec)
    text, finish_reason = _extract_choice_text(resp.json()["choices"][0])
    if want_json and not parse_json_response(text) and (finish_reason == "length" or text.lstrip().startswith(("{", "```"))):
        payload["max_tokens"] = max(effective_max_tokens * 2, 4096)
        if supports_reasoning_effort and "2.5" in model_l and "pro" not in model_l:
            payload["reasoning_effort"] = "none"
        resp = _post_with_400_fallback(requests, url, headers, payload, timeout_sec)
        text, _ = _extract_choice_text(resp.json()["choices"][0])
    return text


class VLMTool(PluginToolBase):
    """Domain-agnostic VLM API client accepting Image, Prompt, System_Prompt, and Trigger."""

    plugin_id = "theft_recognition_plugin"
    category = "Theft Recognition"
    tool_name = "VLM"
    description = (
        "Generic Vision-Language Model API caller. Accepts Image + Prompt (+ optional System_Prompt and Trigger), "
        "handles provider/API config, and outputs Response_Text and Response_JSON."
    )

    param_definitions = {
        "mode": ParamDef(
            "mode",
            ParamType.ENUM,
            "Cloud / OpenAI-Compatible API",
            "Execution backend",
            choices=["Cloud / OpenAI-Compatible API", "Dry-Run (Echo Inputs)"],
        ),
        "provider": ParamDef(
            "provider",
            ParamType.ENUM,
            "openai",
            "VLM provider",
            choices=["openai", "deepseek", "gemini", "anthropic", "openrouter", "ollama", "lmstudio", "custom"],
        ),
        "base_url": ParamDef("base_url", ParamType.STRING, "", "Optional API base URL override"),
        "model_name": ParamDef("model_name", ParamType.STRING, "gpt-4o-mini", "Vision model ID"),
        "api_key": ParamDef("api_key", ParamType.STRING, "", "API key (blank = env var / saved key)"),
        "temperature": ParamDef("temperature", ParamType.FLOAT, 0.1, "Sampling temperature", 0.0, 2.0, 0.05),
        "max_tokens": ParamDef("max_tokens", ParamType.INT, 2048, "Max completion tokens", 64, 8192, 64),
        "timeout_sec": ParamDef("timeout_sec", ParamType.FLOAT, 25.0, "HTTP request timeout", 2.0, 120.0, 1.0, unit="s"),
        "async_non_blocking": ParamDef("async_non_blocking", ParamType.BOOLEAN, True, "Run VLM HTTP request in background"),
        "max_concurrent": ParamDef("max_concurrent", ParamType.INT, 1, "Max concurrent async VLM requests", 1, 8, 1),
        "parse_json": ParamDef("parse_json", ParamType.BOOLEAN, True, "Extract Response_JSON object from completion text"),
    }

    def _init_ports(self):
        self.inputs["Image"] = ToolPort("Image", DataType.IMAGE, "Image or sequence grid to analyze")
        self.inputs["Frames"] = ToolPort("Frames", DataType.ANY, "Optional chronological list of JPEG bytes or frames")
        self.inputs["Prompt"] = ToolPort("Prompt", DataType.STRING, "User prompt generated upstream (e.g. Script)")
        self.inputs["System_Prompt"] = ToolPort("System_Prompt", DataType.STRING, "Optional system prompt")
        self.inputs["Trigger"] = ToolPort("Trigger", DataType.BOOLEAN, "Only invoke VLM when True (unwired = always)")
        self.outputs["Image"] = ToolPort("Image", DataType.IMAGE, "Pass-through image")
        self.outputs["Response_Text"] = ToolPort("Response_Text", DataType.STRING, "Raw VLM completion text")
        self.outputs["Response_JSON"] = ToolPort("Response_JSON", DataType.ANY, "Parsed JSON dict (if parse_json)")
        self.outputs["Has_Response"] = ToolPort("Has_Response", DataType.BOOLEAN, "True for 1 cycle when fresh reply arrives")
        self.outputs["Has_Error"] = ToolPort("Has_Error", DataType.BOOLEAN, "True when the last or completed VLM call failed")
        self.outputs["Error"] = ToolPort("Error", DataType.STRING, "Failure detail when VLM request fails (empty if OK)")
        self.outputs["Status"] = ToolPort("Status", DataType.STRING, "OK | PENDING | IDLE | NO_API_KEY | ERROR")

    def _init_parameters(self):
        self.parameters = {k: copy.deepcopy(p.default_value) for k, p in self.param_definitions.items()}
        self._lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._executor_workers: int = 0
        self._inflight_list: Deque[Tuple[Future, Optional[np.ndarray]]] = deque()
        self._pending_queue: Deque[Tuple[Dict[str, Any], Optional[np.ndarray]]] = deque(maxlen=16)
        self._last_img: Optional[np.ndarray] = None
        self._last_text = ""
        self._last_json: Dict[str, Any] = {}
        self._last_error = ""

    def _get_executor(self, workers: int = 2) -> ThreadPoolExecutor:
        target = max(2, int(workers))
        if self._executor is None or self._executor_workers < target:
            if self._executor is not None:
                self._executor.shutdown(wait=False)
            self._executor = ThreadPoolExecutor(max_workers=target, thread_name_prefix="apex-vlm")
            self._executor_workers = target
        return self._executor

    def execute(self, context: Dict[str, Any]) -> ToolExecutionResult:
        frame = context.get("Image")
        frames_raw = context.get("Frames")
        trigger_in = context.get("Trigger")
        prompt = str(context.get("Prompt") or "").strip()
        sys_prompt = str(context.get("System_Prompt") or "").strip()

        mode = str(self.get_param("mode", "Cloud / OpenAI-Compatible API"))
        provider = str(self.get_param("provider", "openai"))
        base_url_override = str(self.get_param("base_url", ""))
        model_name = str(self.get_param("model_name", "gpt-4o-mini")).strip() or "gpt-4o-mini"
        api_key_override = str(self.get_param("api_key", ""))
        temperature = max(0.0, min(2.0, float(self.as_float(self.get_param("temperature", 0.1), 0.1))))
        max_tokens = max(32, int(self.as_float(self.get_param("max_tokens", 512), 512)))
        timeout_sec = max(2.0, float(self.as_float(self.get_param("timeout_sec", 25.0), 25.0)))
        async_mode = bool(self.get_param("async_non_blocking", True))
        max_concurrent = max(1, min(8, int(self.as_float(self.get_param("max_concurrent", 1), 1))))
        want_json = bool(self.get_param("parse_json", True))

        fresh_reply = False
        err_msg = ""
        out_img = frame
        frames_b64 = _encode_frames_b64(frames_raw) if frames_raw else []

        with self._lock:
            if self._inflight_list and self._inflight_list[0][0].done():
                fut, submitted_img = self._inflight_list.popleft()
                try:
                    self._last_text = fut.result()
                    self._last_json = parse_json_response(self._last_text) if want_json else {}
                    if submitted_img is not None:
                        self._last_img = submitted_img
                        out_img = submitted_img
                    self._last_error = ""
                    fresh_reply = True
                except Exception as exc:
                    err_msg = f"VLM request failed: {exc}"
                    self._last_error = err_msg

            should_fire = (trigger_in is None or bool(trigger_in)) and bool(
                prompt or frames_b64 or (isinstance(frame, np.ndarray) and frame.size > 0)
            )
            if should_fire:
                if mode == "Dry-Run (Echo Inputs)":
                    self._last_text = json.dumps({
                        "echo_prompt": prompt[:200],
                        "has_image": isinstance(frame, np.ndarray) or bool(frames_b64),
                        "frame_count": len(frames_b64) if frames_b64 else (1 if isinstance(frame, np.ndarray) and frame.size > 0 else 0),
                    })
                    self._last_json = parse_json_response(self._last_text) if want_json else {}
                    self._last_img = frame
                    self._last_error = ""
                    fresh_reply = True
                else:
                    _, base_url, api_key = resolve_endpoint_and_key(provider, base_url_override, api_key_override)
                    needs_key = provider not in ("ollama", "lmstudio")
                    if not base_url:
                        err = "VLM Base URL is empty for provider 'custom'."
                        self._last_error = err
                        return ToolExecutionResult(
                            status=ToolStatus.ERROR,
                            message=err,
                            outputs={
                                "Image": frame,
                                "Response_Text": "",
                                "Response_JSON": {},
                                "Has_Response": False,
                                "Has_Error": True,
                                "Error": err,
                                "Status": "ERROR",
                            },
                        )
                    if needs_key and not api_key:
                        return ToolExecutionResult(
                            status=ToolStatus.OK,
                            message=f"VLM skipped (no API key for '{provider}')",
                            outputs={
                                "Image": frame,
                                "Response_Text": self._last_text,
                                "Response_JSON": self._last_json,
                                "Has_Response": False,
                                "Has_Error": False,
                                "Error": "",
                                "Status": "NO_API_KEY",
                            },
                        )

                    img_b64 = _encode_image_b64(frame) if not frames_b64 else ""
                    req_kwargs = dict(
                        provider=provider,
                        base_url=base_url,
                        api_key=api_key,
                        model_name=model_name,
                        prompt=prompt or "Describe the image.",
                        system_prompt=sys_prompt,
                        image_b64=img_b64,
                        frames_b64=frames_b64,
                        want_json=want_json,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout_sec=timeout_sec,
                    )
                    frame_copy = frame.copy() if isinstance(frame, np.ndarray) else None
                    if async_mode:
                        self._pending_queue.append((req_kwargs, frame_copy))
                    elif not err_msg:
                        try:
                            self._last_text = call_generic_vlm(**req_kwargs)
                            self._last_json = parse_json_response(self._last_text) if want_json else {}
                            self._last_img = frame
                            self._last_error = ""
                            fresh_reply = True
                        except Exception as exc:
                            err_msg = f"VLM request failed: {exc}"
                            self._last_error = err_msg

            while async_mode and len(self._inflight_list) < max_concurrent and self._pending_queue:
                next_kwargs, next_img = self._pending_queue.popleft()
                fut = self._get_executor(max_concurrent).submit(call_generic_vlm, **next_kwargs)
                self._inflight_list.append((fut, next_img))

            if err_msg:
                return ToolExecutionResult(
                    status=ToolStatus.ERROR,
                    message=err_msg,
                    outputs={
                        "Image": out_img,
                        "Response_Text": "",
                        "Response_JSON": {},
                        "Has_Response": False,
                        "Has_Error": True,
                        "Error": err_msg,
                        "Status": "ERROR",
                    },
                )

            queued_n = len(self._pending_queue)
            inflight_n = len(self._inflight_list)
            status_tag = "OK" if fresh_reply else ("PENDING" if (inflight_n > 0 or queued_n > 0) else "IDLE")
            detail = (
                f" ({len(self._last_text)} chars)"
                if fresh_reply
                else (f" (queued: {queued_n})" if queued_n > 0 else "")
            )
            return ToolExecutionResult(
                status=ToolStatus.OK,
                message=f"VLM {status_tag}{detail}",
                outputs={
                    "Image": out_img,
                    "Response_Text": self._last_text,
                    "Response_JSON": self._last_json,
                    "Has_Response": fresh_reply,
                    "Has_Error": False,
                    "Error": "",
                    "Status": status_tag,
                },
            )
