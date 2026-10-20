"""Measured usability criteria for the QML window (targets, text, contrast, keyboard, feedback)."""
import pytest

pytest.importorskip("PyQt6.QtQml")
from PyQt6.QtCore import Qt

from test_qml_interaction import fresh, ui  # noqa: F401
from test_qml_sweep import MENU, open_menu
from usability_audit import audit

from PyQt6.QtGui import QGuiApplication

# the offscreen platform used by CI has no fonts (glyph boxes), so text-width checks only run on a real display
import os
REAL_FONTS = os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen", "minimal")
DIALOGS = {"globalVars", "flowSettings", "validate", "cameraSet", "lensCal", "newSolution", "plugins", "about", "manual"}


def real_small_targets(found):
    return list(found["small_targets"])


def test_main_screen_meets_target_size_and_text_size(ui):
    ui.settle()
    for tab in (0, 1, 2):
        ui.main.setProperty("workspaceTab", tab)
        ui.spin(30)
        r = audit(ui, f"tab{tab}")
        assert not real_small_targets(r), f"tab {tab}: click targets under 24x22 px: {real_small_targets(r)}"
        assert not r["small_text"], f"tab {tab}: text under 11 px: {r['small_text']}"
        if REAL_FONTS:
            assert not r["truncated"] and not r["overflow"], (r["truncated"], r["overflow"])
    ui.main.setProperty("workspaceTab", 0)


@pytest.mark.parametrize("title,text,key", [m for m in MENU if m[2] in DIALOGS], ids=lambda v: v if len(str(v)) < 14 else None)
def test_dialogs_meet_target_size_text_size_and_contrast(ui, title, text, key):
    open_menu(ui, title)
    ui.click_text(text)
    ui.spin(40)
    frames = [f for f in ui.host.childItems() if f.isVisible() and f.width() > 100]
    assert frames
    r = audit(ui, key, frames[0])
    ui.close_dialog()
    assert not real_small_targets(r), real_small_targets(r)
    assert not r["small_text"], r
    if REAL_FONTS:
        assert not r["truncated"] and not r["overflow"], r
    assert not r["low_contrast"], f"text below WCAG AA contrast: {r['low_contrast']}"


def test_keyboard_only_flow_in_a_dialog(ui):
    """Tab reaches the dialog's controls, Space/Enter activates them, Esc leaves."""
    ui.main.setProperty("workspaceTab", 0)
    ui.host.setProperty("current", "flowSettings")
    ui.spin(40)
    seen = set()
    for _ in range(12):
        ui.key(Qt.Key.Key_Tab)
        item = ui.w.activeFocusItem()
        if item is not None:
            seen.add(item.metaObject().className())
    assert len(seen) >= 2, f"Tab never moved focus through the dialog controls: {seen}"
    ui.key(Qt.Key.Key_Escape)
    assert ui.dialog == ""


def test_switch_and_checkbox_toggle_from_the_keyboard(ui):
    ui.host.setProperty("current", "flowSettings")
    ui.spin(40)
    boxes = [c for c in ui.of_type("CheckLabel") if c.isVisible()]
    assert boxes
    box = boxes[0]
    before = box.property("checked")
    box.forceActiveFocus()
    ui.key(Qt.Key.Key_Space)
    assert box.property("checked") != before
    ui.key(Qt.Key.Key_Escape)


def test_number_box_arrow_keys_and_wheel(ui):
    ui.host.setProperty("current", "flowSettings")
    ui.spin(40)
    nb = next(c for c in ui.of_type("NumberBox") if c.isVisible())
    v = nb.property("value")
    step = nb.property("step")
    ui.click(ui.center(nb))
    ui.key(Qt.Key.Key_Up)
    assert nb.property("value") == pytest.approx(v + step)
    ui.key(Qt.Key.Key_Down)
    assert nb.property("value") == pytest.approx(v)
    ui.key(Qt.Key.Key_Escape)


def test_every_action_gives_feedback(ui):
    """Heuristic 1 (visibility of status): editing actions announce themselves in the status bar."""
    n = ui.be.nodes[0]["id"]
    ui.be.hint
    for action, expect in ((lambda: ui.be.arrange(), "arranged"), (lambda: ui.be.deleteNode(n), "Deleted"),
                           (lambda: ui.be.undo(), "")):
        action()
        ui.spin(20)
        assert ui.be.hint, "no status message after an editing action"
        if expect:
            assert expect in ui.be.hint


def _ai_fixture(ui, tmp_path, configured):
    from test_qml_aigen import FakeStore
    from vm_clone.flowgen.settings import AISettings
    svc = ui.engine._services["appAI"]
    svc._store = FakeStore()
    svc._settings = AISettings(str(tmp_path / "ai.json"))
    svc._session_keys = {"anthropic": "sk-ant-test-0000000000000000"} if configured else {}
    svc._settings.configured = configured
    svc._messages, svc._busy = [], False
    svc.changed.emit()
    return svc


def test_ai_gen_settings_and_chat_meet_target_text_and_contrast_criteria(ui, tmp_path):
    for configured in (False, True):                          # first-run settings pop-up, then the chat
        svc = _ai_fixture(ui, tmp_path, configured)
        ui.main.setProperty("aiVisible", False)
        ui.spin(10)
        ui.main.setProperty("aiVisible", True)
        ui.spin(40)
        panel = next(c for c in ui.of_type("AiChatPanel"))
        panel.setProperty("settingsOpen", not configured)
        ui.spin(30)
        r = audit(ui, "ai", panel)
        assert not real_small_targets(r), (configured, real_small_targets(r))
        assert not r["small_text"], r["small_text"]
        assert not r["low_contrast"], (configured, r["low_contrast"])
    ui.main.setProperty("aiVisible", False)


def test_ai_gen_is_keyboard_operable(ui, tmp_path):
    _ai_fixture(ui, tmp_path, False)
    ui.main.setProperty("aiVisible", False)
    ui.spin(10)
    ui.main.setProperty("aiVisible", True)
    ui.spin(40)
    seen = set()
    for _ in range(10):
        ui.key(Qt.Key.Key_Tab)
        item = ui.w.activeFocusItem()
        if item is not None:
            seen.add(item.metaObject().className())
    assert len(seen) >= 3, f"Tab did not reach the settings controls: {seen}"
    assert next(c for c in ui.of_type("AiChatPanel")).isVisible(), "Tab must stay inside the panel"
    ui.main.setProperty("aiVisible", False)
