"""Extract KEYENCE UI screenshots from the official manuals.

Renders pages and extracts embedded images so the palette can be measured from
real pixels rather than guessed.  Also ranks pages by how UI-dense their text is,
so the screen-layout pages are found without reading 1000+ pages by hand.

Run:  python scripts/extract_keyence_refs.py
"""
import json
import os
import re
import sys
from typing import Dict, List, Tuple

import pypdfium2 as pdfium

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "docs", "references", "keyence")
OUT = os.path.join(SRC, "pages")
FIGS = os.path.join(SRC, "figs")
INDEX = os.path.join(SRC, "index.json")

#: Terms that mark a page as describing the on-screen interface.
UI_TERMS = (
    "window", "toolbar", "menu", "screen", "display area", "panel",
    "button", "list", "pane", "tab", "icon", "layout", "dialog",
)

#: Vendor/product words to skip so the ranking is about UI, not about marketing.
NOISE = ("copyright", "trademark", "warranty", "specification")


def page_text(page) -> str:
    try:
        return page.get_textpage().get_text_range() or ""
    except Exception:
        return ""


def score(text: str) -> int:
    low = text.lower()
    if any(n in low for n in NOISE):
        return 0
    return sum(low.count(t) for t in UI_TERMS)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(FIGS, exist_ok=True)

    index: Dict[str, List[Dict]] = {}
    for name in sorted(os.listdir(SRC)):
        if not name.lower().endswith(".pdf"):
            continue
        path = os.path.join(SRC, name)
        print(f"\n=== {name}")
        try:
            pdf = pdfium.PdfDocument(path)
        except Exception as exc:
            print(f"  cannot open: {exc}")
            continue

        n = len(pdf)
        print(f"  {n} pages")
        ranked: List[Tuple[int, int, str]] = []
        for i in range(n):
            try:
                text = page_text(pdf[i])
            except Exception:
                continue
            s = score(text)
            if s >= 6:
                ranked.append((s, i, text))
        ranked.sort(reverse=True, key=lambda r: r[0])
        print(f"  {len(ranked)} UI-dense pages; top:")
        for s, i, _t in ranked[:10]:
            print(f"    page {i + 1:4d}  score {s}")

        stem = os.path.splitext(name)[0]
        entries: List[Dict] = []
        # Render the 24 most UI-dense pages at a readable scale.
        for s, i, text in ranked[:24]:
            page = pdf[i]
            try:
                bitmap = page.render(scale=2.4)
                img = bitmap.to_pil()
            except Exception as exc:
                print(f"    render failed p{i + 1}: {exc}")
                continue
            out = os.path.join(OUT, f"{stem}_p{i + 1:04d}.png")
            img.save(out)
            entries.append({"page": i + 1, "score": s, "file": out,
                            "excerpt": re.sub(r"\s+", " ", text)[:400]})
            # Save embedded images too: manuals often carry the UI as a figure.
            try:
                for k, obj in enumerate(page.get_objects()):
                    if not isinstance(obj, pdfium.PdfImage):
                        continue
                    pil = obj.to_pil()
                    if pil.width < 200 or pil.height < 150:
                        continue
                    f = os.path.join(FIGS, f"{stem}_p{i + 1:04d}_img{k}.png")
                    pil.save(f)
            except Exception:
                pass

        index[name] = entries
        pdf.close()

    with open(INDEX, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1)
    print(f"\nwrote {INDEX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
