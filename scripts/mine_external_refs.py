"""Mine the external VisionMaster reference PDFs for UI evidence.

Extracts both the embedded UI figures and the surrounding page text so the
interface structure can be read from the vendor's own documentation, and writes
an index under ``docs/references/external/`` for use as design evidence.
"""
import os
import sys
import json

import pypdfium2 as pdfium

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXT = os.path.join(ROOT, "docs", "references", "external")

# (document, first page, last page, figure tag) - 1-based, inclusive.
TARGETS = [
    ("visionmaster_v4.3.0_user_manual_cn.pdf", 1, 120, "vm43"),
    ("visionmaster_interface_paper_cn.pdf", 1, 40, "iface"),
    ("visionmaster_3d_v2.2.0_user_manual_cn.pdf", 1, 60, "vm3d"),
]

MIN_W = 500
MIN_H = 300


def page_text(pdf, index: int, limit: int = 4000) -> str:
    try:
        tp = pdf[index].get_textpage()
        return tp.get_text_range(0, min(limit, tp.count_chars()))
    except Exception:
        return ""


def main() -> int:
    os.makedirs(EXT, exist_ok=True)
    fig_dir = os.path.join(EXT, "figs")
    os.makedirs(fig_dir, exist_ok=True)

    index = {}
    for doc_name, start, end, tag in TARGETS:
        path = os.path.join(EXT, doc_name)
        if not os.path.exists(path):
            print(f"skip {doc_name} (not downloaded)")
            continue

        pdf = pdfium.PdfDocument(path)
        print(f"\n=== {doc_name}: {len(pdf)} pages; scanning {start}-{end}")
        doc_index = {"pages": len(pdf), "figures": [], "text": {}}
        saved = 0

        for page_no in range(start, min(end, len(pdf)) + 1):
            page = pdf[page_no - 1]
            text = page_text(pdf, page_no - 1)
            if text.strip():
                doc_index["text"][str(page_no)] = text

            try:
                objects = page.get_objects()
            except Exception:
                continue
            n = 0
            for obj in objects:
                try:
                    if obj.type != 3:
                        continue
                    img = obj.get_bitmap(render=False)
                    if img is None:
                        continue
                    pil = img.to_pil()
                    if pil.width < MIN_W or pil.height < MIN_H:
                        continue
                    n += 1
                    saved += 1
                    fname = f"{tag}_p{page_no:03d}_{n:02d}.png"
                    pil.save(os.path.join(fig_dir, fname))
                    doc_index["figures"].append(fname)
                except Exception:
                    continue
        print(f"    figures saved: {saved}")
        index[doc_name] = doc_index

    with open(os.path.join(EXT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    print(f"\nindex written to {os.path.join(EXT, 'index.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
