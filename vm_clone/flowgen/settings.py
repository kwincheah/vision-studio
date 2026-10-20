"""AI Gen's non-secret settings (provider, model and server address per provider), stored as JSON."""
import json
import os
from typing import Any, Dict

from vm_clone.flowgen import providers


def default_path() -> str:
    from PyQt6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation) or os.path.expanduser("~/.apex_vision")
    return os.path.join(base, "ai_gen.json")


class AISettings:
    def __init__(self, path: str = ""):
        self.path = path or default_path()
        self.provider = providers.DEFAULT_PROVIDER
        self.models: Dict[str, str] = {}
        self.base_urls: Dict[str, str] = {}
        self.configured = False                     # the user has completed the settings dialog at least once
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        pid = data.get("provider")
        self.provider = pid if any(p["id"] == pid for p in providers.PROVIDERS) else providers.DEFAULT_PROVIDER
        self.models = self._strings(data.get("models"))
        self.base_urls = self._strings(data.get("base_urls"))
        self.configured = bool(data.get("configured"))

    @staticmethod
    def _strings(value: Any) -> Dict[str, str]:
        return {str(k): v for k, v in value.items() if isinstance(v, str)} if isinstance(value, dict) else {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"provider": self.provider, "models": self.models, "base_urls": self.base_urls,
                       "configured": self.configured}, f, indent=1)

    def model_for(self, provider: str) -> str:
        return self.models.get(provider) or providers.default_model(provider)

    def base_url_for(self, provider: str) -> str:
        return self.base_urls.get(provider) or providers.get(provider)["base_url"]
