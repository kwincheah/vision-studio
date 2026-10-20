"""Model providers AI Gen can talk to, and how to reach them.

Two wire protocols cover them all: the Anthropic Messages API (Claude) and the OpenAI-style Chat Completions
API, which OpenAI, Google Gemini, Mistral, DeepSeek, xAI, Groq, OpenRouter, Ollama, LM Studio and any custom
server speak.  Model lists are curated defaults; ``fetch_models`` asks the provider for the real list, and the
settings dialog also accepts any model id typed by hand.
"""
import os
from typing import Any, Dict, List, Optional

ANTHROPIC = "anthropic"

PROVIDERS: List[Dict[str, Any]] = [
    {"id": "anthropic", "label": "Anthropic (Claude)", "protocol": "anthropic", "base_url": "https://api.anthropic.com",
     "needs_key": True, "key_prefix": "sk-ant-", "key_placeholder": "sk-ant-...", "env": ["ANTHROPIC_API_KEY"],
     "key_url": "https://console.anthropic.com/settings/keys", "editable_url": False,
     "models": [("claude-sonnet-5-5", "Claude Sonnet 5.5 (balanced)"), ("claude-opus-5-5", "Claude Opus 5.5 (most capable)"),
                ("claude-haiku-5-5", "Claude Haiku 5.5 (fastest, cheapest)")]},
    {"id": "openai", "label": "OpenAI", "protocol": "openai", "base_url": "https://api.openai.com/v1",
     "needs_key": True, "key_prefix": "sk-", "key_placeholder": "sk-...", "env": ["OPENAI_API_KEY"],
     "key_url": "https://platform.openai.com/api-keys", "editable_url": True,
     "models": [("gpt-4.1", "GPT-4.1"), ("gpt-4.1-mini", "GPT-4.1 mini"), ("gpt-4o", "GPT-4o"), ("gpt-4o-mini", "GPT-4o mini")]},
    {"id": "gemini", "label": "Google Gemini", "protocol": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "needs_key": True, "key_prefix": "", "key_placeholder": "AIza...", "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
     "key_url": "https://aistudio.google.com/apikey", "editable_url": True,
     "models": [("gemini-2.5-pro", "Gemini 2.5 Pro"), ("gemini-2.5-flash", "Gemini 2.5 Flash"), ("gemini-2.0-flash", "Gemini 2.0 Flash")]},
    {"id": "mistral", "label": "Mistral AI", "protocol": "openai", "base_url": "https://api.mistral.ai/v1",
     "needs_key": True, "key_prefix": "", "key_placeholder": "API key", "env": ["MISTRAL_API_KEY"],
     "key_url": "https://console.mistral.ai/api-keys", "editable_url": True,
     "models": [("mistral-large-latest", "Mistral Large"), ("mistral-medium-latest", "Mistral Medium"), ("mistral-small-latest", "Mistral Small")]},
    {"id": "deepseek", "label": "DeepSeek", "protocol": "openai", "base_url": "https://api.deepseek.com/v1",
     "needs_key": True, "key_prefix": "sk-", "key_placeholder": "sk-...", "env": ["DEEPSEEK_API_KEY"],
     "key_url": "https://platform.deepseek.com/api_keys", "editable_url": True,
     "models": [("deepseek-chat", "DeepSeek Chat (V3)")]},
    {"id": "xai", "label": "xAI (Grok)", "protocol": "openai", "base_url": "https://api.x.ai/v1",
     "needs_key": True, "key_prefix": "xai-", "key_placeholder": "xai-...", "env": ["XAI_API_KEY"],
     "key_url": "https://console.x.ai", "editable_url": True,
     "models": [("grok-4", "Grok 4"), ("grok-3", "Grok 3"), ("grok-3-mini", "Grok 3 mini")]},
    {"id": "groq", "label": "Groq", "protocol": "openai", "base_url": "https://api.groq.com/openai/v1",
     "needs_key": True, "key_prefix": "gsk_", "key_placeholder": "gsk_...", "env": ["GROQ_API_KEY"],
     "key_url": "https://console.groq.com/keys", "editable_url": True,
     "models": [("llama-3.3-70b-versatile", "Llama 3.3 70B"), ("llama-3.1-8b-instant", "Llama 3.1 8B (instant)")]},
    {"id": "openrouter", "label": "OpenRouter", "protocol": "openai", "base_url": "https://openrouter.ai/api/v1",
     "needs_key": True, "key_prefix": "sk-or-", "key_placeholder": "sk-or-...", "env": ["OPENROUTER_API_KEY"],
     "key_url": "https://openrouter.ai/keys", "editable_url": True,
     "models": [("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"), ("openai/gpt-4.1", "GPT-4.1"), ("google/gemini-2.5-pro", "Gemini 2.5 Pro")]},
    {"id": "ollama", "label": "Ollama (local)", "protocol": "openai", "base_url": "http://localhost:11434/v1",
     "needs_key": False, "key_prefix": "", "key_placeholder": "not needed", "env": [],
     "key_url": "https://ollama.com/download", "editable_url": True,
     "models": [("llama3.1", "Llama 3.1"), ("qwen2.5", "Qwen 2.5")]},
    {"id": "lmstudio", "label": "LM Studio (local)", "protocol": "openai", "base_url": "http://localhost:1234/v1",
     "needs_key": False, "key_prefix": "", "key_placeholder": "not needed", "env": [],
     "key_url": "https://lmstudio.ai", "editable_url": True, "models": []},
    {"id": "custom", "label": "Custom (OpenAI-compatible)", "protocol": "openai", "base_url": "",
     "needs_key": False, "key_prefix": "", "key_placeholder": "API key (if the server needs one)", "env": [],
     "key_url": "", "editable_url": True, "models": []},
]

_BY_ID = {p["id"]: p for p in PROVIDERS}
DEFAULT_PROVIDER = "anthropic"


def get(provider_id: str) -> Dict[str, Any]:
    return _BY_ID.get(provider_id) or _BY_ID[DEFAULT_PROVIDER]


def default_model(provider_id: str) -> str:
    models = get(provider_id)["models"]
    return models[0][0] if models else ""


def public_list() -> List[Dict[str, Any]]:
    """What the QML settings dialog needs (no secrets)."""
    return [{"id": p["id"], "label": p["label"], "needsKey": p["needs_key"], "baseUrl": p["base_url"],
             "editableUrl": p["editable_url"], "keyPlaceholder": p["key_placeholder"], "keyUrl": p["key_url"],
             "models": [{"id": m, "label": label} for m, label in p["models"]]} for p in PROVIDERS]


def env_key(provider_id: str) -> str:
    for name in get(provider_id)["env"]:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def key_problem(provider_id: str, key: str) -> str:
    """Why a key cannot be right (empty string when it looks fine)."""
    p, key = get(provider_id), key.strip()
    if not p["needs_key"] and not key:
        return ""
    if not key:
        return "Enter the API key."
    if " " in key or len(key) < 8:
        return "That does not look like an API key."
    if p["key_prefix"] and not key.startswith(p["key_prefix"]):
        return f"{p['label']} keys start with {p['key_prefix']}"
    return ""


# ids of models that cannot hold a conversation (embeddings, speech, images, moderation ...)
_NOT_CHAT = ("embed", "whisper", "tts", "dall-e", "moderation", "audio", "realtime", "image", "imagen", "veo", "transcribe",
             "davinci", "babbage", "search", "computer-use", "aqa", "rerank", "guard", "speech")


def is_chat_model(provider_id: str, model_id: str) -> bool:
    if provider_id in ("ollama", "lmstudio", "custom"):          # local / unknown servers: show everything they list
        return True
    low = model_id.lower()
    return not any(word in low for word in _NOT_CHAT)


def fetch_models(provider_id: str, key: str, base_url: str = "", http_client: Any = None, timeout: float = 15.0,
                 chat_only: bool = True) -> List[str]:
    """Ask the provider which models this key can use.  Raises on failure with a readable message."""
    import httpx
    p = get(provider_id)
    base = (base_url or p["base_url"]).rstrip("/")
    if not base:
        raise ValueError("Enter the server address first.")
    headers: Dict[str, str] = {}
    if p["protocol"] == "anthropic":
        url = base + "/v1/models?limit=100"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        url = base + "/models"
        if key:
            headers["Authorization"] = f"Bearer {key}"
    client = http_client or httpx.Client(timeout=timeout)
    try:
        resp = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ConnectionError(f"Could not reach {base}: {type(exc).__name__}") from None
    if resp.status_code in (401, 403):
        raise PermissionError("The server rejected the API key.")
    if resp.status_code >= 400:
        raise RuntimeError(f"The server answered {resp.status_code}.")
    data = resp.json()
    items = data.get("data", data.get("models", []))
    ids = [(i.get("id") or i.get("name") or "").removeprefix("models/") for i in items if isinstance(i, dict)]
    return sorted({i for i in ids if i and (not chat_only or is_chat_model(provider_id, i))})
