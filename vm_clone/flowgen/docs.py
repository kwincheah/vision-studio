"""Retrieval over the flow-generation reference (what the assistant's ``search_docs`` / ``read_doc`` tools use).

The reference is split into sections (one per ``##`` / ``###`` heading, so every tool and every recipe is
its own section).  Retrieval is lexical - word overlap with the section title weighted above the body -
which is exact, needs no index or embedding model, and is deterministic.
"""
import os
import re
from functools import lru_cache
from typing import Dict, List, Optional

from vm_clone.flowgen.reference_gen import REFERENCE

_WORD = re.compile(r"[a-z0-9_]+")


class Section(dict):
    """{'id', 'title', 'level', 'text'}"""


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


@lru_cache(maxsize=1)
def sections() -> List[Section]:
    with open(REFERENCE, encoding="utf-8") as f:
        text = f.read()
    out: List[Section] = []
    cur: Optional[Section] = None
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{2,3}) (.+)$", line)
        if m:
            cur = Section(id=_slug(m.group(2)), title=m.group(2).strip(), level=len(m.group(1)), text="")
            out.append(cur)
        elif cur is not None:
            cur["text"] += line + "\n"
    seen: Dict[str, int] = {}
    for s in out:                                       # keep ids unique
        n = seen.get(s["id"], 0)
        seen[s["id"]] = n + 1
        if n:
            s["id"] = f"{s['id']}-{n + 1}"
        s["text"] = s["text"].strip()
    return out


def list_sections() -> List[Dict[str, str]]:
    return [{"id": s["id"], "title": s["title"], "level": s["level"]} for s in sections()
            if not s["title"].startswith("Tool catalogue") or s["level"] == 2]


def read_section(section_id: str) -> Optional[Dict[str, str]]:
    key = section_id.strip().lower()
    for s in sections():
        if s["id"] == key or s["title"].lower() == key:
            return {"id": s["id"], "title": s["title"], "text": s["text"]}
    return None


def search_docs(query: str, limit: int = 4, max_chars: int = 2500) -> List[Dict[str, str]]:
    """Best-matching sections for a free-text query (title matches count triple)."""
    words = set(_WORD.findall(query.lower()))
    scored = []
    for s in sections():
        title_words = set(_WORD.findall(s["title"].lower()))
        body_words = _WORD.findall(s["text"].lower())
        score = 3 * len(words & title_words) + sum(1 for w in body_words if w in words) / (1 + len(body_words) ** 0.5)
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda t: -t[0])
    return [{"id": s["id"], "title": s["title"], "text": s["text"][:max_chars]} for _sc, s in scored[:limit]]
