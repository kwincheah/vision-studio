"""Where the user's API keys live (one per provider).

Order of use: the key typed in this session, else the OS credential store (Windows Credential Manager, macOS
Keychain, Secret Service) when the user chose "Remember", else the provider's environment variable
(``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY`` ...).  Keys are never written to a project file, a log or the
settings file.
"""
import logging
from typing import Optional

from apex_vision.flowgen import providers

logger = logging.getLogger("apex_vision.flowgen")
SERVICE = "ApexVisionStudio"


def _account(provider: str) -> str:
    return "anthropic_api_key" if provider == "anthropic" else f"api_key.{provider}"


def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def can_remember() -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        return "fail" not in type(kr.get_keyring()).__module__.lower()
    except Exception:
        return False


def load_saved(provider: str = "anthropic") -> str:
    kr = _keyring()
    if kr is None:
        return ""
    try:
        return kr.get_password(SERVICE, _account(provider)) or ""
    except Exception as exc:
        logger.warning("Could not read the saved API key: %s", type(exc).__name__)
        return ""


def save(provider_or_key: str, key: Optional[str] = None) -> bool:
    provider, key = ("anthropic", provider_or_key) if key is None else (provider_or_key, key)
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(SERVICE, _account(provider), key)
        return True
    except Exception as exc:
        logger.warning("Could not save the API key: %s", type(exc).__name__)
        return False


def forget(provider: str = "anthropic") -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, _account(provider))
    except Exception:
        pass


def from_environment(provider: str = "anthropic") -> str:
    return providers.env_key(provider)


def looks_valid(key: str, provider: str = "anthropic") -> bool:
    return not providers.key_problem(provider, key)


def mask(key: str) -> str:
    return f"{key[:7]}...{key[-4:]}" if len(key) > 14 else ("set" if key else "")
