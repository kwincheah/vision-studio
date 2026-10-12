"""Render a wide range of manual pages and keep only substantial embedded figures.

VisionMaster's manual (chapter "Software Introduction") embeds the real UI
screenshots as page images; text-only pages are skipped automatically.
"""
import os
import sys

import pypdfium2 as pdfium

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PDF = os.path.join(ROOT, "HikRobotVMHelp_compressed.pdf")
OUT = os.path.join(ROOT, "docs", "references", "figs")

START = int(sys.argv[1]) if len(sys.argv) > 1 else 37
END = int(sys.argv[2]) if len(sys.argv) > 2 else 100
MIN_W = int(sys.argv[3]) if len(sys.argv) > 3 else 420
MIN_H = int(sys.argv[4]) if len(sys.argv) > 4 else 280


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    pdf = pdfium.PdfDocument(PDF)
    total = 0
    for page_no in range(START, END + 1):
        page = pdf[page_no - 1]
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
                total += 1
                fpath = os.path.join(OUT, f"p{page_no:03d}_{n:02d}.png")
                pil.save(fpath)
                print(f"p{page_no:03d}_{n:02d}: {pil.width}x{pil.height}")
            except Exception:
                continue
    print(f"saved {total} figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
