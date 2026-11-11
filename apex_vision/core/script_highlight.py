"""Syntax highlighting and checking for the script editor.

Highlighting is done here rather than in QML because Python already ships a real
tokenizer: ``tokenize`` knows exactly which words are keywords, which strings are
f-strings, where a comment starts and where an operator ends.  A regular expression in
JavaScript would get quoting and multi-line strings wrong.

The editor renders the HTML behind a transparent text field, so the output is a single
string of spans - no coordinates, nothing to keep in sync but the font.
"""
import html
import io
import keyword
import tokenize
from typing import Any, Dict, List, Tuple

#: Token class -> (QML token name, whether it is part of a name chain).
#: The order here is the order the editor's colour map expects.
CLASSES = ("keyword", "builtin", "string", "number", "comment", "operator", "def", "plain")

def _builtin_names():
    """Every name Python treats as built-in, whichever shape ``__builtins__`` has."""
    table = __builtins__
    names = set(table) if isinstance(table, dict) else set(dir(table))
    return frozenset(names) | {
        "print", "len", "range", "int", "float", "str", "bool", "list", "dict", "tuple",
        "set", "min", "max", "sum", "abs", "round", "sorted", "enumerate", "zip",
        "isinstance", "Exception", "ValueError", "True", "False", "None",
    }


BUILTINS = _builtin_names()


def _spans(source: str) -> List[Tuple[int, int, str]]:
    """(start, end, class) for the whole source, tolerant of half-typed code."""
    out: List[Tuple[int, int, str]] = []
    try:
        stream = io.StringIO(source).readline
        for tok in tokenize.generate_tokens(stream):
            kind, text = tok.type, tok.string
            start = sum(len(line) for line in source.splitlines(True)[:tok.start[0] - 1]) \
                + tok.start[1]
            end = start + len(text)
            if kind == tokenize.COMMENT:
                cls = "comment"
            elif kind == tokenize.STRING or (hasattr(tokenize, "FSTRING_MIDDLE")
                                             and kind == tokenize.FSTRING_MIDDLE):
                cls = "string"
            elif kind == tokenize.NUMBER:
                cls = "number"
            elif kind == tokenize.NAME:
                if keyword.iskeyword(text):
                    cls = "keyword"
                elif text in BUILTINS:
                    cls = "builtin"
                else:
                    cls = "plain"
            elif kind == tokenize.OP:
                cls = "operator"
            else:
                continue
            if text.strip() == "":
                continue
            out.append((start, end, cls))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # The buffer is usually mid-edit; highlight what tokenized cleanly and leave the
        # rest plain.  `check_script` is what reports the error to the user.
        pass
    return out


def highlight(source: Any) -> str:
    """The script as HTML with one span per token, ready for Text.RichText."""
    text = "" if source is None else str(source)
    spans = _spans(text)
    if not spans:
        return html.escape(text).replace("\n", "<br/>")
    parts: List[str] = []
    cursor = 0
    for start, end, cls in spans:
        if start < cursor or start > len(text) or end > len(text):
            continue
        parts.append(html.escape(text[cursor:start]))
        chunk = html.escape(text[start:end])
        parts.append(f'<span class="{cls}">{chunk}</span>' if cls != "plain" else chunk)
        cursor = end
    parts.append(html.escape(text[cursor:]))
    return "".join(parts).replace("\n", "<br/>")


def check(source: Any) -> Dict[str, Any]:
    """Compile the script without running it.

    Returns ``{ok, line, message}``: the line number is 1-based and 0 when unknown, which
    is what the gutter highlights.
    """
    text = "" if source is None else str(source)
    if not text.strip():
        return {"ok": False, "line": 0, "message": "The script is empty."}
    try:
        compile(text, "<script>", "exec")
    except SyntaxError as exc:
        return {"ok": False, "line": int(exc.lineno or 0),
                "message": f"{exc.msg} (line {exc.lineno})"}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "line": 0, "message": str(exc)}
    return {"ok": True, "line": 0, "message": "No syntax errors."}


def describe_contract() -> str:
    """A one-line reminder of what the surrounding module passes in and expects back."""
    return "The script receives `values` and must return the text to send."
