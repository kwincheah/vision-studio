"""AI Gen: the floating chat that builds flows (QML service).

Provider, model, server address and API key are chosen in the settings dialog (shown automatically the first
time AI Gen opens).  The conversation runs on a worker thread (``FlowAgent.run_turn``); its events come back
through a queued signal so every change to the QML-visible state happens on the GUI thread.
"""
import json
import threading
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot

from vm_clone.qml_backend import AppBackend


def _path(url: str) -> str:
    return QUrl(url).toLocalFile() or url


class AIGenService(QObject):
    changed = pyqtSignal()
    _event = pyqtSignal(object)

    def __init__(self, app: AppBackend, settings_path: str = ""):
        super().__init__()
        from vm_clone.flowgen import keystore, providers
        from vm_clone.flowgen.settings import AISettings
        self._app = app
        self._store = keystore
        self._providers = providers
        self._settings = AISettings(settings_path)
        self._session_keys: Dict[str, str] = {}
        self._sources: Dict[str, str] = {}
        self._error = ""
        self._messages: List[Dict[str, Any]] = []
        self._flows: Dict[int, Dict[str, Any]] = {}
        self._busy = False
        self._agent = None
        self._carry = None
        self._thread: Optional[threading.Thread] = None
        self._fetched: Dict[str, List[str]] = {}          # provider -> model ids the account can use
        self._fetching = False
        self._models_version = 0
        self._models_provider = ""
        self._models_state = ""
        self._models_message = ""
        self._test_state = ""
        self._test_message = ""
        self.client_factory = None                       # tests inject a fake client for every provider
        self.http_client = None                          # tests inject a fake HTTP transport for the REST calls
        self._event.connect(self._on_event)
        self._migrate_configured()

    def _migrate_configured(self) -> None:
        """A key that is already available (saved or in the environment) counts as configured."""
        s = self._settings
        if not s.configured and self._key(s.provider):
            s.configured = True

    # ---- keys
    def _key(self, provider: str) -> str:
        if provider in self._session_keys:
            return self._session_keys[provider]
        saved = self._store.load_saved(provider)
        if saved:
            self._sources[provider] = "saved"
            return saved
        env = self._store.from_environment(provider)
        if env:
            self._sources[provider] = "environment"
        return env

    def _ready(self) -> bool:
        p = self._providers.get(self._settings.provider)
        return self._settings.configured and (not p["needs_key"] or bool(self._key(p["id"])))

    # ---- state for QML
    @pyqtProperty("QVariantList", constant=True)
    def providerList(self):  # noqa: N802
        return self._providers.public_list()

    @pyqtProperty(str, notify=changed)
    def provider(self):
        return self._settings.provider

    @pyqtProperty(str, notify=changed)
    def model(self):
        return self._settings.model_for(self._settings.provider)

    @pyqtProperty(str, notify=changed)
    def baseUrl(self):  # noqa: N802
        return self._settings.base_url_for(self._settings.provider)

    @pyqtProperty(str, notify=changed)
    def subtitle(self):
        p = self._providers.get(self._settings.provider)
        return f"{p['label'].split(' (')[0]} · {self.model or 'no model'}"

    @pyqtProperty(bool, notify=changed)
    def ready(self):
        return self._ready()

    @pyqtProperty(str, notify=changed)
    def settingsError(self):  # noqa: N802
        return self._error

    @pyqtProperty(bool, constant=True)
    def canRemember(self):  # noqa: N802
        return self._store.can_remember()

    @pyqtProperty(bool, notify=changed)
    def busy(self):
        return self._busy

    @pyqtProperty(int, notify=changed)
    def modelsVersion(self):  # noqa: N802
        return self._models_version                   # bumps whenever a provider's model list changes (re-evaluates bindings)

    @pyqtProperty(str, notify=changed)
    def modelsProvider(self):  # noqa: N802
        return self._models_provider

    @pyqtProperty(str, notify=changed)
    def modelsState(self):  # noqa: N802
        return self._models_state                     # "", "loading", "ok", "error" for the last list request

    @pyqtProperty(str, notify=changed)
    def modelsMessage(self):  # noqa: N802
        return self._models_message

    @pyqtSlot(str, result="QVariantList")
    def modelsFor(self, provider):  # noqa: N802
        """Suggestions for the model field: the account's real list once loaded (with friendly names where known),
        otherwise the curated defaults."""
        curated = {m[0]: m[1] for m in self._providers.get(provider)["models"]}
        ids = self._fetched.get(provider)
        if ids:
            return [{"id": i, "label": curated.get(i, "")} for i in ids]
        return [{"id": i, "label": label} for i, label in curated.items()]

    @pyqtSlot(str, str, result=str)
    def modelWarning(self, provider, model):  # noqa: N802
        ids = self._fetched.get(provider)
        if ids and model.strip() and model.strip() not in ids and provider not in ("openrouter", "custom"):
            return "This model is not in the list the account can use. It may fail."
        return ""

    @pyqtSlot(str)
    def setModel(self, model_id):  # noqa: N802
        """Switch the model of the current provider (the header's quick picker)."""
        model_id = model_id.strip()
        if not model_id:
            return
        s = self._settings
        s.models[s.provider] = model_id
        s.save()
        if self._agent is not None:
            self._agent.model = model_id
        self.changed.emit()

    @pyqtProperty(bool, notify=changed)
    def fetching(self):
        return self._fetching

    @pyqtProperty(str, notify=changed)
    def testState(self):  # noqa: N802
        return self._test_state

    @pyqtProperty(str, notify=changed)
    def testMessage(self):  # noqa: N802
        return self._test_message

    @pyqtProperty("QVariantList", notify=changed)
    def messages(self):
        return self._messages

    @pyqtProperty(int, notify=changed)
    def messageCount(self):  # noqa: N802
        return len(self._messages)

    @pyqtProperty("QVariantMap", notify=changed)
    def tokens(self):
        return dict(self._agent.tokens) if self._agent else {"input": 0, "output": 0}

    @pyqtSlot(str, result=str)
    def keyHintFor(self, provider):  # noqa: N802
        """Masked key already available for ``provider`` ('' when none) and where it came from."""
        key = self._key(provider)
        return self._store.mask(key) if key else ""

    @pyqtSlot(str, result=str)
    def keySourceFor(self, provider):  # noqa: N802
        if provider in self._session_keys:
            return "session"
        self._key(provider)
        return self._sources.get(provider, "")

    @pyqtSlot(str, result=str)
    def savedModelFor(self, provider):  # noqa: N802
        return self._settings.model_for(provider)

    @pyqtSlot(str, result=str)
    def savedBaseUrlFor(self, provider):  # noqa: N802
        return self._settings.base_url_for(provider)

    # ---- settings
    @pyqtSlot(str, str, str, str, bool, result=bool)
    def saveSettings(self, provider, base_url, model, key, remember):  # noqa: N802
        pr = self._providers
        spec = pr.get(provider)
        key, model, base_url = key.strip(), model.strip(), base_url.strip().rstrip("/")
        if provider not in [p["id"] for p in pr.PROVIDERS]:
            return self._fail("Choose a provider.")
        if spec["editable_url"] and not base_url:
            return self._fail("Enter the server address.")
        if not model:
            return self._fail("Choose or type a model.")
        if key or (spec["needs_key"] and not self._key(provider)):
            problem = pr.key_problem(provider, key)
            if problem:
                return self._fail(problem)
        s = self._settings
        if key:
            self._session_keys[provider] = key
            self._sources[provider] = "session"
            if remember:
                if self._store.save(provider, key):
                    self._sources[provider] = "saved"
                    self._session_keys.pop(provider, None)
        s.provider = provider
        s.models[provider] = model
        if spec["editable_url"]:
            s.base_urls[provider] = base_url
        s.configured = True
        s.save()
        self._error = ""
        self._agent_changed()
        self.changed.emit()
        return True

    def _fail(self, message: str) -> bool:
        self._error = message
        self.changed.emit()
        return False

    @pyqtSlot(str)
    def removeKey(self, provider):  # noqa: N802
        self._store.forget(provider)
        self._session_keys.pop(provider, None)
        self._sources.pop(provider, None)
        self._agent_changed()
        self.changed.emit()

    @pyqtSlot()
    def clearError(self):  # noqa: N802
        self._error = ""
        self._test_state = self._test_message = ""
        self.changed.emit()

    # ---- connection test and model list (background)
    def _run_async(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    @pyqtSlot(str, str, str)
    def fetchModels(self, provider, base_url, key):  # noqa: N802
        key = key.strip() or self._key(provider)
        if self._providers.get(provider)["needs_key"] and not key:
            return                                       # nothing to ask yet: the curated suggestions stay
        self._fetching = True
        self._models_provider, self._models_state, self._models_message = provider, "loading", "Loading models..."
        self.changed.emit()

        def work():
            try:
                ids = self._providers.fetch_models(provider, key, base_url.strip(), http_client=self.http_client)
                self._event.emit({"type": "models", "ids": ids, "provider": provider})
            except Exception as exc:
                self._event.emit({"type": "models", "ids": [], "provider": provider, "error": str(exc)})
        self._run_async(work)

    @pyqtSlot(str, str, str, str)
    def testConnection(self, provider, base_url, model, key):  # noqa: N802
        key = key.strip() or self._key(provider)
        problem = self._providers.key_problem(provider, key)
        if problem and self._providers.get(provider)["needs_key"]:
            self._test_state, self._test_message = "error", problem
            self.changed.emit()
            return
        self._test_state, self._test_message = "testing", "Testing the connection..."
        self.changed.emit()

        def work():
            try:
                ids = self._providers.fetch_models(provider, key, base_url.strip(), http_client=self.http_client)
                note = ""
                if model and ids and model not in ids and provider not in ("openrouter", "custom"):
                    note = f" The model '{model}' is not in the list this key can use."
                self._event.emit({"type": "test", "ok": True, "message": f"Connected. {len(ids)} models available.{note}"})
            except Exception as exc:
                self._event.emit({"type": "test", "ok": False, "message": str(exc) or type(exc).__name__})
        self._run_async(work)

    # ---- conversation
    def _agent_changed(self) -> None:
        """Provider, model or key changed: a new agent continues the same conversation."""
        old = self._agent
        self._agent = None
        if old is not None and not self._busy:
            self._carry = old.messages
        else:
            self._carry = None

    def _client_factory(self):
        if self.client_factory is not None:
            return self.client_factory
        spec = self._providers.get(self._settings.provider)
        if spec["protocol"] == "anthropic":
            return None
        from vm_clone.flowgen.openai_compat import OpenAICompatClient
        base = self._settings.base_url_for(spec["id"])
        return lambda key: OpenAICompatClient(key, base, http_client=self.http_client)

    def _make_agent(self):
        from vm_clone.flowgen import api
        from vm_clone.flowgen.agent import FlowAgent
        agent = FlowAgent(self._key(self._settings.provider), self.model,
                          current_flow=lambda: api.pipeline_to_spec(self._app._pipeline), client_factory=self._client_factory())
        carried = getattr(self, "_carry", None)
        if carried:
            agent.messages = carried
        self._carry = None
        return agent

    @pyqtSlot(str)
    def send(self, text):
        text = text.strip()
        if not text or self._busy or not self._ready():
            return
        if self._agent is None:
            self._agent = self._make_agent()
        self._messages.append({"role": "user", "text": text, "tools": [], "flowIndex": -1, "error": ""})
        self._messages.append({"role": "assistant", "text": "", "tools": [], "flowIndex": -1, "error": ""})
        self._busy = True
        self.changed.emit()
        agent = self._agent
        self._thread = threading.Thread(target=lambda: agent.run_turn(text, self._event.emit), daemon=True)
        self._thread.start()

    @pyqtSlot()
    def stop(self):
        if self._agent:
            self._agent.cancel()

    @pyqtSlot()
    def newChat(self):  # noqa: N802
        if self._busy:
            return
        self._messages, self._flows, self._agent, self._carry = [], {}, None, None
        self.changed.emit()

    def wait(self, timeout: float = 10.0) -> None:
        """Block until the running turn has finished (tests)."""
        if self._thread:
            self._thread.join(timeout)

    def _on_event(self, ev):
        kind = ev.get("type")
        if kind == "models":
            self._fetching = False
            self._models_provider = ev["provider"]
            if ev.get("error"):
                self._models_state, self._models_message = "error", ev["error"]
            else:
                self._fetched[ev["provider"]] = ev["ids"]
                self._models_version += 1
                self._models_state = "ok"
                self._models_message = f"{len(ev['ids'])} models available." if ev["ids"] else "The account lists no models."
            self.changed.emit()
            return
        if kind == "test":
            self._test_state = "ok" if ev["ok"] else "error"
            self._test_message = ev["message"]
            self.changed.emit()
            return
        last = self._messages[-1] if self._messages else None
        if kind == "text" and last:
            last["text"] += ev["delta"]
        elif kind == "tool" and last:
            last["tools"] = last["tools"] + [{"summary": ev["summary"], "ok": bool(ev["ok"])}]
        elif kind == "flow" and last:
            spec = ev["spec"]
            idx = len(self._flows)
            self._flows[idx] = {"spec": spec, "xml": ev["xml"]}
            last["flowIndex"] = idx
            last["flow"] = {"summary": ev["summary"], "modules": len(spec["modules"]), "links": len(spec.get("links", [])),
                            "names": [m["tool"] for m in spec["modules"]],
                            "warnings": [i["message"] for i in ev["issues"] if i["severity"] == "warning"],
                            "sideEffects": ev["side_effects"], "applied": False}
        elif kind == "error" and last:
            last["error"] = ev["message"]
        elif kind == "notice" and last:
            last["text"] += ("\n\n" if last["text"] else "") + ev["message"]
        elif kind == "done":
            self._busy = False
        self.changed.emit()

    # ---- results
    @pyqtSlot(int, str, result=bool)
    def applyFlow(self, index, mode):  # noqa: N802
        entry = self._flows.get(index)
        if entry is None:
            return False
        ok = self._app.applyGeneratedFlow(json.dumps(entry["spec"]), mode)
        if ok:
            for m in self._messages:
                if m.get("flowIndex") == index and "flow" in m:
                    m["flow"] = dict(m["flow"], applied=True)
            self.changed.emit()
        return ok

    @pyqtSlot(int, str)
    def saveXml(self, index, url):  # noqa: N802
        entry = self._flows.get(index)
        if entry:
            with open(_path(url), "w", encoding="utf-8") as f:
                f.write(entry["xml"])
            self._app._notify(f"Saved flow XML to {_path(url)}")

    @pyqtSlot(int)
    def copyXml(self, index):  # noqa: N802
        entry = self._flows.get(index)
        if entry:
            from PyQt6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(entry["xml"])
            self._app._notify("Flow XML copied to the clipboard")
