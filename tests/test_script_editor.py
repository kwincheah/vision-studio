"""The script editor's highlighting and checking, and the editor's structure."""
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from apex_vision.core import script_highlight as sh   # noqa: E402

QML = os.path.join(ROOT, "qml")


def code(rel):
    text = open(os.path.join(QML, rel), encoding="utf-8").read()
    return "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())


# ---------------------------------------------------------------- highlighting
def test_keywords_strings_comments_and_numbers_are_classified():
    html = sh.highlight("def f(x):\n    # note\n    return 'a' + 42\n")
    assert 'class="keyword">def' in html
    assert 'class="comment"># note' in html
    assert 'class="string">' in html
    assert 'class="number">42' in html


def test_builtins_are_classified():
    html = sh.highlight("print(len([1, 2]))")
    assert html.count('class="builtin"') == 2, html


def test_html_is_escaped_so_a_script_cannot_inject_markup():
    html = sh.highlight("x = '<b>bold</b> & more'")
    assert "&lt;b&gt;" in html
    assert "<b>" not in html
    assert "&amp;" in html


def test_newlines_become_breaks():
    assert sh.highlight("a = 1\nb = 2").count("<br/>") == 1


def test_empty_source_is_safe():
    assert sh.highlight("") == ""
    assert sh.highlight(None) == ""


def test_half_typed_code_still_highlights_what_it_can():
    """The buffer is mid-edit almost all the time; this must never raise."""
    for partial in ("def ", "def f(", "class X", "x = 'unterminated", "    "):
        assert isinstance(sh.highlight(partial), str)


# ---------------------------------------------------------------- checking
def test_a_valid_script_checks_ok():
    result = sh.check("def f(values):\n    return ','.join(map(str, values))\n")
    assert result["ok"] is True
    assert result["line"] == 0


def test_a_syntax_error_reports_its_line():
    result = sh.check("x = 1\ndef f(:\n    pass\n")
    assert result["ok"] is False
    assert result["line"] == 2


def test_an_empty_script_is_rejected():
    result = sh.check("   \n")
    assert result["ok"] is False
    assert "empty" in result["message"].lower()


def test_indentation_errors_are_reported():
    result = sh.check("def f():\nreturn 1\n")
    assert result["ok"] is False
    assert result["line"] >= 1


# ---------------------------------------------------------------- the widget
def test_the_editor_component_is_registered():
    qmldir = open(os.path.join(QML, "ApexComponents", "qmldir"), encoding="utf-8").read()
    assert "ScriptEditor 1.0 ScriptEditor.qml" in qmldir
    assert qmldir.splitlines()[0].startswith("module "), (
        "the module directive must stay first in a qmldir")


def test_the_editor_has_the_features_of_a_small_ide():
    text = code("ApexComponents/ScriptEditor.qml")
    for feature in ("lineCount",            # line numbers
                    "highlightScript",      # syntax colours
                    "checkScript",          # inline error
                    "errorLine",
                    "Key_Tab",              # indentation
                    "Key_Slash",            # comment toggle
                    "currentColumn"):       # Ln/Col readout
        assert feature in text, f"the editor lost: {feature}"


def test_the_editor_lays_the_highlight_behind_the_caret():
    """The two layers must share a font and start at the same place, or the text doubles."""
    text = code("ApexComponents/ScriptEditor.qml")
    assert "textFormat: Text.RichText" in text
    assert "color: \"transparent\"" in text, "the editable layer must not paint glyphs"
    assert "font: code.font" in text, "the layers must use the same font"


def test_code_parameters_use_the_script_editor():
    text = code("ApexComponents/ParamEditor.qml")
    assert "ScriptEditor" in text
    start = text.find("Component { id: codeEditor")
    end = text.find("Component { id: pathEditor")
    assert 0 < start < end
    assert "ScriptEditor" in text[start:end]


@pytest.mark.parametrize("token", ["syntaxKeyword", "syntaxBuiltin", "syntaxString",
                                   "syntaxNumber", "syntaxComment", "syntaxOperator",
                                   "syntaxPlain"])
def test_syntax_colours_clear_aa_on_the_editor_background(token):
    theme = open(os.path.join(QML, "ApexTheme", "Theme.qml"), encoding="utf-8").read()
    cols = {m.group(1): m.group(2).lower() for m in
            re.finditer(r'readonly property color (\w+)\s*:\s*"(#[0-9a-fA-F]{6})"', theme)}

    def srgb(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h):
        r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)

    bg, fg = cols["fieldBg"], cols[token]
    la, lb = lum(bg), lum(fg)
    ratio = (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    assert ratio >= 4.5, f"{token} is {ratio:.2f}:1 on the editor background"


# ---------------------------------------------------------------- scrollbars
def test_no_unthemed_scrollbar_remains():
    """A bare `ScrollBar { }` renders near-black under a native style."""
    offenders = []
    for dirpath, _d, files in os.walk(QML):
        for name in files:
            if not name.endswith(".qml"):
                continue
            path = os.path.join(dirpath, name)
            text = code(os.path.relpath(path, QML).replace("\\", "/"))
            if re.search(r"ScrollBar(\.vertical|\.horizontal)?\s*:\s*ScrollBar\s*\{", text):
                offenders.append(os.path.relpath(path, ROOT))
    assert not offenders, f"unthemed ScrollBar left in: {offenders}"


def test_the_controls_style_is_pinned_to_a_stylable_one():
    text = open(os.path.join(ROOT, "apex_vision", "qml_app.py"), encoding="utf-8").read()
    assert "QT_QUICK_CONTROLS_STYLE" in text and "Basic" in text


# ---------------------------------------------------------------- layout ratio
def test_the_image_block_takes_six_of_ten():
    text = code("screens/MainScreen.qml")
    assert "imageBlockShare: 0.6" in text
    assert "imageBlockShare" in text.split("height:")[0] or "imageBlockShare" in text
    # the viewport must size from the share, not a constant
    m = re.search(r"id: viewport\b[\s\S]{0,1400}?height:\s*([\s\S]{0,320})", text)
    assert m, "viewport height not found"
    # the expression spans several lines, so match the whole block
    assert "imageBlockShare" in m.group(1), (
        f"the image viewport is still a fixed height: {m.group(1).strip()[:90]}")
