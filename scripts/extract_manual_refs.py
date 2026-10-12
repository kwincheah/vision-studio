"""Extract reference pages / figures from the official VisionMaster manual PDF.

Uses pypdfium2 (already available) to render full pages and to pull embedded
figure images so the UI can be compared against the real product.
"""
import os
import sys
import json

import pypdfium2 as pdfium

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PDF = os.path.join(ROOT, "HikRobotVMHelp_compressed.pdf")
OUT = os.path.join(ROOT, "docs", "references")

# 1-based page numbers that document the UI chrome (menu / toolbar / toolbox /
# result display / flow management) per manual_outline.json.
PAGES = [37, 39, 41, 69, 70, 72, 81, 88, 92, 93, 151, 158]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    pdf = pdfium.PdfDocument(PDF)
    print(f"PDF pages: {len(pdf)}")

    for page_no in PAGES:
        idx = page_no - 1
        if idx < 0 or idx >= len(pdf):
            continue
        page = pdf[idx]
        bitmap = page.render(scale=2.0)
        pil = bitmap.to_pil()
        path = os.path.join(OUT, f"page_{page_no:03d}.png")
        pil.save(path)
        print(f"page {page_no}: {pil.width}x{pil.height} -> {path}")

        # Extract embedded figure images (skip tiny icons / page furniture).
        try:
            objects = page.get_objects()
        except Exception as exc:  # pragma: no cover - defensive
            print(f"  object scan failed: {exc}")
            continue

        n_saved = 0
        for obj in objects:
            try:
                if obj.type != 3:  # FPDF_PAGEOBJ_IMAGE
                    continue
                img = obj.get_bitmap(render=False)
                if img is None:
                    continue
                sub = img.to_pil()
                if sub.width < 180 or sub.height < 120:
                    continue
                n_saved += 1
                fpath = os.path.join(OUT, f"p{page_no:03d}_fig{n_saved:02d}.png")
                sub.save(fpath)
                print(f"  fig {n_saved}: {sub.width}x{sub.height} -> {fpath}")
            except Exception:
                continue

    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
