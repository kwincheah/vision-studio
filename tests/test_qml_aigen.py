"""AI Gen in the QML window: toolbar button, first-run settings pop-up (provider / key / model), the chat, the
three-dot menu and a full prompt -> flow round trip - operated with real mouse and keyboard events.  The
provider APIs are replaced by fake HTTP transports / clients; the OS credential store is never touched."""
import json
import time

import pytest

pytest.importorskip("PyQt6.QtQml")
httpx = pytest.importorskip("httpx")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from test_flowgen import GOOD, FakeClient, call, text
from test_flowgen_providers import chat_chunks, sse
from test_qml_interaction import fresh, ui  # noqa: F401
from apex_vision.flowgen import keystore, providers
from apex_vision.flowgen.settings import AISettings

KEY = "sk-ant-test-key-000000000000000"
OPENAI_KEY = "sk-openai-test-0000000000000"


class FakeStore:
    """The OS credential store must never be touched by tests (one slot per provider)."""
    def __init__(self):
        self.saved = {}

    def can_remember(self):
        return True

    def load_saved(self, provider="anthropic"):
        return self.saved.get(provider, "")

    def save(self, provider, key):
        self.saved[provider] = key
        return True

    def forget(self, provider="anthropic"):
        self.saved.pop(provider, None)

    def from_environment(self, provider="anthropic"):
        return ""

    mask = staticmethod(keystore.mask)


@pytest.fixture
def ai(ui, tmp_path):
    svc = ui.engine._services["appAI"]
    svc._store = FakeStore()
    svc._settings = AISettings(str(tmp_path / "ai.json"))            # fresh: nothing configured
    svc._session_keys, svc._sources, svc._error = {}, {}, ""
    svc._agent = svc._carry = None
    svc._messages, svc._flows, svc._busy = [], {}, False
    svc._fetched, svc._test_state, svc._test_message = {}, "", ""
    svc._models_provider = svc._models_state = svc._models_message = ""
    svc.client_factory = svc.http_client = None
    svc.changed.emit()
    pn = panel(ui)
    pn.setProperty("settingsOpen", False)
    input_box(ui).setProperty("text", "")
    ui.main.setProperty("aiVisible", False)
    ui.spin(25)
    yield svc
    svc.wait(5)
    ui.main.setProperty("aiVisible", False)
    svc.client_factory = svc.http_client = None
    svc._settings = AISettings(str(tmp_path / "gone.json"))
    svc.changed.emit()


def panel(ui):
    return next(c for c in ui.of_type("AiChatPanel"))


def button(ui):
    return next(c for c in ui.of_type("ChromePillButton"))


def by_name(ui, cls, name, visible=True):
    return next(t for t in ui.walk() if cls in t.metaObject().className() and t.property("objectName") == name and (t.isVisible() or not visible))


def input_box(ui):
    return by_name(ui, "TextEdit", "aiInput", visible=False)


def settings_view(ui):
    return by_name(ui, "Rectangle", "aiSettings", visible=False) if False else next(
        c for c in ui.walk() if c.property("objectName") == "aiSettings" and "AiSettings" in c.metaObject().className())


def open_panel(ui):
    ui.click(ui.center(button(ui)))
    assert ui.main.property("aiVisible") is True
    ui.spin(40)
    return panel(ui)


def type_text(ui, s):
    for ch in s:
        QTest.keyClick(ui.w, ch)
    ui.spin(5)


def click_field(ui, name):
    ui.click(ui.center(by_name(ui, "TextBox", name)))


def field_text(ui, name):
    box = by_name(ui, "TextBox", name)
    return next(i.property("text") for i in ui.walk(box) if "TextInput" in i.metaObject().className())


def press(ui, name):
    ui.click(ui.center(by_name(ui, "AppButton", name)))
    ui.spin(20)


def wait_idle(ui, ai, timeout=10):
    end = time.time() + timeout
    while (ai.busy or (ai._thread and ai._thread.is_alive())) and time.time() < end:
        ui.spin(3)
    ai.wait(2)
    ui.spin(30)


def wait_for(ui, cond, timeout=8):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        ui.spin(3)
    ui.spin(20)
    return cond()


def choose(ui, box_name, label):
    """Open a drop-down and click the entry below it (the selected value is shown in the box itself)."""
    box = by_name(ui, "SelectBox", box_name)
    ui.click(ui.center(box))
    ui.spin(15)
    y0 = ui.center(box).y()
    entry = next(t for t in ui.texts(label) if ui.center(t).y() > y0 + 5)
    ui.click(ui.center(entry))
    ui.spin(30)


def configure(ui, ai, provider="anthropic", key=KEY, model=""):
    """Drive the real settings dialog (provider list, key field, Save) the way a person does."""
    open_panel(ui)
    if provider != "anthropic":
        choose(ui, "aiProvider", next(p["label"] for p in providers.PROVIDERS if p["id"] == provider))
    if key:
        click_field(ui, "aiKeyField")
        type_text(ui, key)
    if model:
        mf = by_name(ui, "TextBox", "aiModelField")
        ui.click(ui.center(mf))
        ui.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text(ui, model)
    press(ui, "aiSave")
    assert ai.ready, ai.settingsError


# ---------------------------------------------------------------- toolbar, menu, shortcut
def test_toolbar_button_opens_and_closes_the_floating_chat(ui, ai):
    btn = button(ui)
    assert btn.property("text") == "AI Gen" and btn.isVisible()
    p = open_panel(ui)
    assert p.isVisible() and p.width() >= 340
    ui.click(ui.center(btn))
    assert ui.main.property("aiVisible") is False
    open_panel(ui)
    ui.key(Qt.Key.Key_Escape)
    assert ui.main.property("aiVisible") is False


def test_ctrl_g_and_the_tools_menu_open_the_chat(ui, ai):
    ui.key(Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier)
    assert ui.main.property("aiVisible") is True
    ui.key(Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier)
    assert ui.main.property("aiVisible") is False
    from test_qml_sweep import open_menu
    open_menu(ui, "Tools")
    ui.click_text("AI Gen - Build a Flow from a Description...")
    assert ui.main.property("aiVisible") is True


def test_the_chat_floats_it_can_be_dragged_and_resized(ui, ai):
    p = open_panel(ui)
    x0, y0, h0 = p.x(), p.y(), p.height()
    top = ui.point_in(p, 300, 20)                            # empty part of the title bar (the model chip is to its left)
    ui.drag(top, QPoint(top.x() - 120, top.y() + 60))
    p = panel(ui)
    assert p.x() < x0 - 60 and p.y() > y0 + 30
    w1 = p.width()
    grip = ui.point_in(p, 8, p.height() - 8)
    ui.drag(grip, QPoint(grip.x() - 80, grip.y() + 20))
    assert panel(ui).width() > w1 + 40 and panel(ui).height() >= h0


# ---------------------------------------------------------------- first run: the settings pop up
def test_first_open_pops_up_the_settings_instead_of_the_chat(ui, ai):
    assert not ai.ready
    p = open_panel(ui)
    assert p.property("settingsOpen") is True and settings_view(ui).isVisible()
    assert ui.texts("Set up AI Gen") and ui.texts("Provider") and ui.texts("API key") and ui.texts("Model")
    assert not input_box(ui).isVisible(), "the chat must not be usable before a provider and key are set"


def test_the_provider_list_has_the_major_providers(ui, ai):
    open_panel(ui)
    ui.click(ui.center(by_name(ui, "SelectBox", "aiProvider")))
    for label in ("Anthropic (Claude)", "OpenAI", "Google Gemini", "Mistral AI", "DeepSeek", "xAI (Grok)", "Groq", "OpenRouter",
                  "Ollama (local)", "LM Studio (local)", "Custom (OpenAI-compatible)"):
        assert ui.texts(label), f"{label} missing from the provider list"
    ui.key(Qt.Key.Key_Escape)


def test_choosing_a_provider_switches_address_key_hint_and_models(ui, ai):
    open_panel(ui)
    choose(ui, "aiProvider", "OpenAI")
    assert field_text(ui, "aiBaseUrl") == "https://api.openai.com/v1"
    assert field_text(ui, "aiModelField") == "gpt-4.1"
    assert by_name(ui, "TextBox", "aiKeyField").property("placeholder") == "sk-..."
    choose(ui, "aiProvider", "Anthropic (Claude)")
    assert field_text(ui, "aiModelField") == "claude-sonnet-5-5"
    assert not any(t.isVisible() for t in ui.walk() if t.property("objectName") == "aiBaseUrl"), "Claude has a fixed address"


def test_saving_needs_a_valid_key_and_explains_what_is_wrong(ui, ai):
    open_panel(ui)
    press(ui, "aiSave")
    assert not ai.ready and ai.settingsError == "Enter the API key."
    assert ui.texts("Enter the API key.")
    click_field(ui, "aiKeyField")
    type_text(ui, "not-a-claude-key")
    press(ui, "aiSave")
    assert "start with sk-ant-" in ai.settingsError and not ai.ready


def test_the_key_field_hides_the_key_until_show_key_is_ticked(ui, ai):
    open_panel(ui)
    field = by_name(ui, "TextBox", "aiKeyField")
    assert field.property("echoMode") == 2
    ui.click(ui.center(by_name(ui, "CheckLabel", "aiShowKey")))
    assert field.property("echoMode") == 0


def test_a_valid_key_saves_and_opens_the_chat(ui, ai):
    configure(ui, ai)
    assert ai.provider == "anthropic" and ai.model == "claude-sonnet-5-5" and ai.keySourceFor("anthropic") == "session"
    assert not panel(ui).property("settingsOpen") and input_box(ui).isVisible()
    assert ui.texts("What should the flow do?")
    assert ui.texts("Anthropic · claude-sonnet-5-5")
    assert ai._settings.configured and not ai._store.saved
    assert "sk-ant" not in open(ai._settings.path, encoding="utf-8").read(), "the key must never reach the settings file"


def test_remember_stores_the_key_in_the_credential_store_per_provider(ui, ai):
    open_panel(ui)
    click_field(ui, "aiKeyField")
    type_text(ui, KEY)
    ui.click(ui.center(by_name(ui, "CheckLabel", "aiRemember")))
    press(ui, "aiSave")
    assert ai._store.saved == {"anthropic": KEY} and ai.keySourceFor("anthropic") == "saved"
    assert ai.saveSettings("openai", "https://api.openai.com/v1", "gpt-4.1", OPENAI_KEY, True)
    assert ai._store.saved == {"anthropic": KEY, "openai": OPENAI_KEY}, "each provider keeps its own key"
    ai.removeKey("openai")
    assert ai._store.saved == {"anthropic": KEY}


def test_a_local_provider_needs_no_key(ui, ai):
    configure(ui, ai, provider="ollama", key="")
    assert ai.provider == "ollama" and ai.baseUrl == "http://localhost:11434/v1" and ai.model == "llama3.1"


def test_any_model_id_can_be_typed_and_a_custom_server_address_is_kept(ui, ai):
    open_panel(ui)
    choose(ui, "aiProvider", "Custom (OpenAI-compatible)")
    click_field(ui, "aiBaseUrl")
    type_text(ui, "http://10.0.0.5:8000/v1")
    mf = by_name(ui, "TextBox", "aiModelField")
    ui.click(ui.center(mf))
    type_text(ui, "my-finetune-v2")
    press(ui, "aiSave")
    assert ai.ready and ai.provider == "custom" and ai.model == "my-finetune-v2" and ai.baseUrl == "http://10.0.0.5:8000/v1"
    again = AISettings(ai._settings.path)
    assert again.provider == "custom" and again.model_for("custom") == "my-finetune-v2"


def test_a_missing_server_address_is_reported(ui, ai):
    open_panel(ui)
    choose(ui, "aiProvider", "Custom (OpenAI-compatible)")
    mf = by_name(ui, "TextBox", "aiModelField")
    ui.click(ui.center(mf))
    type_text(ui, "m")
    press(ui, "aiSave")
    assert ai.settingsError == "Enter the server address." and not ai.ready


OPENAI_MODELS = {"data": [{"id": "gpt-5-preview"}, {"id": "gpt-4.1"}, {"id": "o9-mini"}, {"id": "text-embedding-3-large"},
                          {"id": "whisper-1"}, {"id": "dall-e-3"}, {"id": "tts-1"}]}


def models_http(calls=None):
    def handler(req):
        if calls is not None:
            calls.append(str(req.url))
        return httpx.Response(200, json=OPENAI_MODELS)
    return httpx.Client(transport=httpx.MockTransport(handler))


def model_field(ui):
    return by_name(ui, "TextBox", "aiModelField")


def options(ui):
    return [t for t in ui.walk() if t.property("objectName") == "aiModelOption" and t.isVisible()]


def option_texts(ui):
    out = []
    for o in options(ui):
        out += [x.property("text") for x in ui.walk(o) if "QQuickText" in x.metaObject().className() and x.property("text")]
    return out


def test_the_model_is_one_editable_field_not_a_dropdown_plus_a_text_box(ui, ai):
    open_panel(ui)
    fields = [t for t in ui.walk() if t.property("objectName") == "aiModelField" and t.isVisible()]
    assert len(fields) == 1, "exactly one control holds the model"
    assert not [t for t in ui.of_type("SelectBox") if t.isVisible() and t.property("objectName") in ("aiModelList",)]
    assert field_text(ui, "aiModelField") == "claude-sonnet-5-5"


def test_typing_a_model_that_is_not_listed_keeps_exactly_what_was_typed(ui, ai):
    open_panel(ui)
    ui.click(ui.center(model_field(ui)))
    ui.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    type_text(ui, "my-own-model")
    assert field_text(ui, "aiModelField") == "my-own-model", "the field must not jump back to a list entry"
    click_field(ui, "aiKeyField")
    type_text(ui, KEY)
    press(ui, "aiSave")
    assert ai.ready and ai.model == "my-own-model"


def test_suggestions_open_with_the_chevron_and_filter_while_typing(ui, ai):
    open_panel(ui)
    ui.click(ui.center(by_name(ui, "Rectangle", "aiModelToggle")))
    assert {"claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"} <= {t for t in option_texts(ui)}
    ui.click(ui.center(model_field(ui)))
    ui.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    type_text(ui, "opus")
    texts = option_texts(ui)
    assert "claude-opus-5-5" in texts and "claude-haiku-5-5" not in texts


def test_picking_a_suggestion_fills_the_field(ui, ai):
    open_panel(ui)
    ui.click(ui.center(by_name(ui, "Rectangle", "aiModelToggle")))
    haiku = next(o for o in options(ui) if "claude-haiku-5-5" in " ".join(
        x.property("text") for x in ui.walk(o) if "QQuickText" in x.metaObject().className()))
    ui.click(ui.center(haiku))
    assert field_text(ui, "aiModelField") == "claude-haiku-5-5"
    assert not options(ui), "the list closes after a choice"


def test_the_account_model_list_loads_by_itself_once_the_key_is_known_and_hides_non_chat_models(ui, ai):
    calls = []
    ai.http_client = models_http(calls)
    open_panel(ui)
    choose(ui, "aiProvider", "OpenAI")
    assert not calls, "no request is made before there is a key"
    click_field(ui, "aiKeyField")
    type_text(ui, OPENAI_KEY)
    ui.key(Qt.Key.Key_Tab)                                              # leaving the key field loads the list
    assert wait_for(ui, lambda: ai.modelsFor("openai") and ai.modelsFor("openai")[0]["id"] == "gpt-4.1")
    ids = [m["id"] for m in ai.modelsFor("openai")]
    assert ids == ["gpt-4.1", "gpt-5-preview", "o9-mini"], "embeddings, speech and image models are not offered"
    assert calls and calls[0].endswith("/v1/models")
    assert ui.texts("3 models available.")


def test_the_refresh_button_reloads_and_a_list_is_kept_per_provider(ui, ai):
    ai.http_client = models_http()
    ai.saveSettings("anthropic", "", "claude-sonnet-5-5", KEY, False)
    ai.fetchModels("openai", "", OPENAI_KEY)
    assert wait_for(ui, lambda: len(ai.modelsFor("openai")) == 3)
    ai.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": "claude-x"}]})))
    ai.fetchModels("anthropic", "", KEY)
    assert wait_for(ui, lambda: [m["id"] for m in ai.modelsFor("anthropic")] == ["claude-x"])
    assert [m["id"] for m in ai.modelsFor("openai")] == ["gpt-4.1", "gpt-5-preview", "o9-mini"], "the other provider's list is untouched"
    assert [m["id"] for m in ai.modelsFor("mistral")][0] == "mistral-large-latest", "no request yet: curated defaults"
    labelled = {m["id"]: m["label"] for m in ai.modelsFor("openai")}
    assert labelled["gpt-4.1"] == "GPT-4.1"                              # friendly names survive where known


def test_a_failed_list_request_is_explained_next_to_the_model_field_and_does_not_block_saving(ui, ai):
    ai.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    open_panel(ui)
    click_field(ui, "aiKeyField")
    type_text(ui, KEY)
    ui.key(Qt.Key.Key_Tab)
    assert wait_for(ui, lambda: ai.modelsState == "error")
    assert ui.texts("The server rejected the API key.")
    assert [m["id"] for m in ai.modelsFor("anthropic")][0] == "claude-sonnet-5-5"          # suggestions still there
    click_field(ui, "aiKeyField")
    press(ui, "aiSave")
    assert ai.ready


def test_a_model_outside_the_accounts_list_gets_a_warning_but_can_be_saved(ui, ai):
    ai.http_client = models_http()
    ai.fetchModels("openai", "", OPENAI_KEY)
    assert wait_for(ui, lambda: len(ai.modelsFor("openai")) == 3)
    assert ai.modelWarning("openai", "gpt-4.1") == "" and "not in the list" in ai.modelWarning("openai", "gpt-nope")
    assert ai.modelWarning("openrouter", "anything/at-all") == "" and ai.modelWarning("custom", "x") == ""
    assert ai.saveSettings("openai", "https://api.openai.com/v1", "gpt-nope", OPENAI_KEY, False) and ai.model == "gpt-nope"


# ---------------------------------------------------------------- the header model picker
def chip(ui):
    return by_name(ui, "Item", "aiModelChip")


def open_quick(ui, ai):
    ui.click(ui.center(chip(ui)))
    ui.spin(40)
    assert options(ui), "the quick picker did not open"


def test_the_header_shows_provider_and_model_and_is_clickable(ui, ai):
    configure(ui, ai)
    assert ui.texts("Anthropic \u00b7 claude-sonnet-5-5") and chip(ui).isVisible()
    open_quick(ui, ai)
    assert {"claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"} <= set(option_texts(ui))
    assert ui.texts("Change provider or API key...") or any("Change provider" in (t.property("text") or "") for t in ui.of_type("QQuickText"))
    ui.key(Qt.Key.Key_Escape)


def test_picking_a_model_in_the_header_switches_it_at_once_and_remembers_it(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[text("a")], [text("b")]])
    open_quick(ui, ai)
    opus = next(o for o in options(ui) if "claude-opus-5-5" in " ".join(
        x.property("text") for x in ui.walk(o) if "QQuickText" in x.metaObject().className()))
    ui.click(ui.center(opus))
    ui.spin(30)
    assert ai.model == "claude-opus-5-5" and ai.subtitle == "Anthropic \u00b7 claude-opus-5-5"
    assert ui.texts("Anthropic \u00b7 claude-opus-5-5")
    assert AISettings(ai._settings.path).model_for("anthropic") == "claude-opus-5-5"
    assert not panel(ui).property("settingsOpen"), "no settings dialog is needed to switch model"
    ai.send("hello")
    wait_idle(ui, ai)
    assert ai._agent.model == "claude-opus-5-5"


def test_a_typed_model_in_the_header_picker_is_applied_with_enter_and_keeps_the_conversation(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[text("first")], [text("second")]])
    ai.send("hi")
    wait_idle(ui, ai)
    open_quick(ui, ai)
    box = model_field(ui)
    ui.click(ui.center(box))
    ui.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    type_text(ui, "claude-future-9")
    ui.key(Qt.Key.Key_Return)
    ui.spin(30)
    assert ai.model == "claude-future-9" and len(ai.messages) == 2
    ai.send("again")
    wait_idle(ui, ai)
    assert ai._agent.model == "claude-future-9" and ai.messages[-1]["text"] == "second"


def test_the_header_picker_links_to_the_settings_for_provider_changes(ui, ai):
    configure(ui, ai)
    open_quick(ui, ai)
    link = next(t for t in ui.of_type("QQuickText") if t.isVisible() and "Change provider" in (t.property("text") or ""))
    ui.click(ui.center(link))
    ui.spin(30)
    assert panel(ui).property("settingsOpen") is True and ui.texts("AI Gen settings")
    press(ui, "aiCancel")


def test_the_header_picker_does_nothing_before_setup(ui, ai):
    open_panel(ui)                                                       # first-run settings are showing
    assert not ai.ready
    panel(ui).metaObject()
    ui.click(ui.center(chip(ui)))
    ui.spin(30)
    assert not options(ui), "no model list before a provider is set up"


def test_a_local_provider_picker_works_without_any_key_and_lists_what_the_server_has(ui, ai):
    ai.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": "llama3.2"}, {"id": "nomic-embed-text"}]})))
    configure(ui, ai, provider="ollama", key="")
    assert wait_for(ui, lambda: len(ai.modelsFor("ollama")) == 2), "local servers: everything they list is shown"
    open_quick(ui, ai)
    assert {"llama3.2", "nomic-embed-text"} <= set(option_texts(ui))


def test_test_connection_reports_success_and_failure_in_words(ui, ai):
    open_panel(ui)
    press(ui, "aiTest")                                                   # no key yet
    assert ai.testState == "error" and "Enter the API key" in ai.testMessage
    click_field(ui, "aiKeyField")
    type_text(ui, KEY)
    ai.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": "claude-sonnet-5-5"}]})))
    press(ui, "aiTest")
    assert wait_for(ui, lambda: ai.testState == "ok") and "Connected" in ai.testMessage
    assert ui.texts("✓ " + ai.testMessage)
    ai.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    press(ui, "aiTest")
    assert wait_for(ui, lambda: ai.testState == "error") and "rejected the API key" in ai.testMessage


def test_cancel_on_first_run_closes_ai_gen_and_it_asks_again_next_time(ui, ai):
    open_panel(ui)
    press(ui, "aiCancel")
    assert ui.main.property("aiVisible") is False and not ai.ready
    open_panel(ui)
    assert panel(ui).property("settingsOpen") is True


def test_settings_are_not_shown_again_once_configured(ui, ai):
    configure(ui, ai)
    ui.key(Qt.Key.Key_Escape)
    ui.spin(20)
    open_panel(ui)
    assert not panel(ui).property("settingsOpen") and input_box(ui).isVisible()


# ---------------------------------------------------------------- three-dot menu
def dots(ui):
    return by_name(ui, "Rectangle", "aiMenuButton")


def test_three_dot_menu_has_settings_new_chat_and_remove_key(ui, ai):
    configure(ui, ai)
    ui.click(ui.center(dots(ui)))
    for item in ("Settings...", "New chat", "Remove saved API key"):
        assert ui.texts(item), item
    ui.key(Qt.Key.Key_Escape)


def test_settings_from_the_menu_reopen_prefilled_and_cancel_returns_to_the_chat(ui, ai):
    configure(ui, ai, model="claude-opus-5-5")
    ui.click(ui.center(dots(ui)))
    ui.click_text("Settings...")
    ui.spin(30)
    assert panel(ui).property("settingsOpen") is True and ui.texts("AI Gen settings")
    assert field_text(ui, "aiModelField") == "claude-opus-5-5"
    assert ui.texts("Save") and not ui.texts("Save and start")
    press(ui, "aiCancel")
    assert not panel(ui).property("settingsOpen") and input_box(ui).isVisible()


def test_switching_provider_in_settings_keeps_the_conversation(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[text("first answer")]])
    ai.send("hello")
    wait_idle(ui, ai)
    assert ai.saveSettings("openai", "https://api.openai.com/v1", "gpt-4.1", OPENAI_KEY, False)
    assert ai.subtitle == "OpenAI · gpt-4.1" and [m["role"] for m in ai.messages] == ["user", "assistant"]
    ai._agent = ai._make_agent()
    assert any(m["role"] == "user" and m["content"] == "hello" for m in ai._agent.messages)


def test_new_chat_from_the_menu_clears_the_conversation(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[text("hi")]])
    ai.send("hello")
    wait_idle(ui, ai)
    ui.click(ui.center(dots(ui)))
    ui.click_text("New chat")
    ui.spin(20)
    assert not ai.messages and ui.texts("What should the flow do?")


def test_remove_saved_key_from_the_menu_sends_the_user_back_to_settings(ui, ai):
    open_panel(ui)
    click_field(ui, "aiKeyField")
    type_text(ui, KEY)
    ui.click(ui.center(by_name(ui, "CheckLabel", "aiRemember")))
    press(ui, "aiSave")
    ui.click(ui.center(dots(ui)))
    ui.click_text("Remove saved API key")
    ui.spin(30)
    assert not ai._store.saved and not ai.ready
    ui.key(Qt.Key.Key_Escape)
    ui.spin(20)
    open_panel(ui)
    assert panel(ui).property("settingsOpen") is True


# ---------------------------------------------------------------- the chat
def test_example_prompt_chips_fill_the_input_and_enter_sends(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[text("Sure - describe the part and I will build it.")]])
    ui.click_text("Count the bright blobs after smoothing and noise removal")
    box = input_box(ui)
    assert box.property("text").startswith("Count the bright blobs")
    ui.key(Qt.Key.Key_Return)
    wait_idle(ui, ai)
    assert ai.messages[0]["role"] == "user" and ai.messages[1]["text"].startswith("Sure")
    assert box.property("text") == ""
    assert ui.texts("You") and ui.texts("AI Gen")


def test_shift_enter_adds_a_line_instead_of_sending(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[text("x")]])
    ui.click(ui.center(input_box(ui)))
    type_text(ui, "line one")
    ui.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    type_text(ui, "line two")
    assert not ai.messages and "\n" in input_box(ui).property("text")


def test_prompt_to_flow_round_trip_adds_the_flow_and_undo_removes_it(ui, ai):
    configure(ui, ai)
    client = FakeClient([
        [text("Checking the reference. "), call("search_docs", {"query": "count blobs"})],
        [call("propose_flow", {"spec": GOOD, "summary": "Smooth, binarise and count blobs."})],
        [text("Added a flow that smooths, binarises and counts blobs.")]])
    ai.client_factory = lambda k: client
    ui.click(ui.center(input_box(ui)))
    type_text(ui, "count the blobs")
    ui.key(Qt.Key.Key_Return)
    wait_idle(ui, ai)
    assert ui.texts("Smooth, binarise and count blobs.") and ui.texts("4 modules, 3 links")
    assert any("Searched the reference" in t["summary"] for t in ai.messages[1]["tools"])
    flows_before, nodes_before = len(ui.be._solution.flows), len(ui.be.nodes)
    add = next(b for b in ui.of_type("AppButton") if b.property("objectName") == "aiAddFlow" and b.isVisible())
    ui.click(ui.center(add))
    assert len(ui.be._solution.flows) == flows_before + 1 and ui.be.flowName == "Blur_Count" and len(ui.be.nodes) == 4
    assert ui.texts("✓ Added to the project (Ctrl+Z undoes it)")
    ui.be.undo()
    ui.spin(40)
    assert len(ui.be._solution.flows) == flows_before and len(ui.be.nodes) == nodes_before


def test_a_non_claude_provider_drives_the_whole_loop_through_the_adapter(ui, ai):
    """OpenAI selected in the settings: the chat talks Chat Completions (fake HTTP) and still produces a flow."""
    seen = []
    script = [
        (200, sse(chat_chunks(text="Looking it up.", calls=[("c1", "search_docs", json.dumps({"query": "count blobs"}))]))),
        (200, sse(chat_chunks(calls=[("c2", "propose_flow", json.dumps({"spec": GOOD, "summary": "Blob count via OpenAI."}))]))),
        (200, sse(chat_chunks(text="Done."))),
    ]

    def handler(req):
        seen.append((req.headers.get("authorization"), str(req.url), json.loads(req.content)))
        return httpx.Response(200, content=script.pop(0)[1], headers={"content-type": "text/event-stream"})
    ai.http_client = httpx.Client(transport=httpx.MockTransport(handler))
    configure(ui, ai, provider="openai", key=OPENAI_KEY)
    assert ui.texts("OpenAI · gpt-4.1")
    ui.click(ui.center(input_box(ui)))
    type_text(ui, "count the blobs")
    ui.key(Qt.Key.Key_Return)
    wait_idle(ui, ai)
    assert seen[0][0] == f"Bearer {OPENAI_KEY}" and seen[0][1] == "https://api.openai.com/v1/chat/completions"
    assert seen[0][2]["model"] == "gpt-4.1"
    assert ui.texts("Blob count via OpenAI.")
    assert ai.messages[-1]["text"].endswith("Done.") and not ai.messages[-1]["error"]


def test_replace_open_flow_keeps_the_flow_name_and_is_undoable(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[call("propose_flow", {"spec": GOOD, "summary": "s"})], [text("done")]])
    ai.send("x")
    wait_idle(ui, ai)
    name, n = ui.be.flowName, len(ui.be._solution.flows)
    assert ai.applyFlow(0, "replace")
    assert ui.be.flowName == name and len(ui.be._solution.flows) == n and len(ui.be.nodes) == 4
    ui.be.undo()
    ui.spin(40)
    assert len(ui.be.nodes) == 7


def test_locked_projects_refuse_generated_flows(ui, ai):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[call("propose_flow", {"spec": GOOD, "summary": "s"})], [text("done")]])
    ai.send("x")
    wait_idle(ui, ai)
    ui.be.setRole("Operator")
    assert ai.applyFlow(0, "new") is False
    ui.be.setRole("Engineer")


def test_an_api_error_is_shown_in_the_chat(ui, ai):
    configure(ui, ai)

    class Boom:
        def __init__(self):
            self.messages = self

        def stream(self, **kw):
            raise type("AuthenticationError", (Exception,), {})("401")

    ai.client_factory = lambda k: Boom()
    ai.send("hello")
    wait_idle(ui, ai)
    assert "API key was rejected" in ai.messages[-1]["error"] and not ai.busy
    assert ui.texts("The API key was rejected. Check it in AI Gen settings.")


def test_the_key_never_reaches_messages_requests_or_logs(ui, ai, caplog):
    configure(ui, ai)
    client = FakeClient([[text("hello")]])
    ai.client_factory = lambda k: client
    ai.send("hi")
    wait_idle(ui, ai)
    assert KEY not in json.dumps(ai.messages, default=str) and KEY not in caplog.text and KEY not in json.dumps(client.requests)
    assert KEY not in ai.subtitle and KEY not in ai.keyHintFor("anthropic")


def test_xml_can_be_copied_and_saved(ui, ai, tmp_path):
    configure(ui, ai)
    ai.client_factory = lambda k: FakeClient([[call("propose_flow", {"spec": GOOD, "summary": "s"})], [text("ok")]])
    ai.send("x")
    wait_idle(ui, ai)
    ai.copyXml(0)
    from PyQt6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text().startswith("<?xml")
    out = tmp_path / "f.xml"
    ai.saveXml(0, str(out))
    from apex_vision.core.pipeline import SolutionManager
    assert "Blur_Count" in SolutionManager.from_xml(out.read_text(encoding="utf-8")).flows
