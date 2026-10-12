"""Render and crop key UI regions from the external VisionMaster manual.

Produces high-resolution crops of the annotated main-interface figure and the
toolbar / image-display / results figures so each region can be inspected
individually as design evidence.
"""
import os
import sys

import pypdfium2 as pdfium

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXT = os.path.join(ROOT, "docs", "references", "external")
DOC = os.path.join(EXT, "visionmaster_v4.3.0_user_manual_cn.pdf")
OUT = os.path.join(EXT, "ui_crops")

# (page, scale, crop box as fractions (l, t, r, b), name)
CROPS = [
    # Annotated main-interface figure (region map 1-13)
    (38, 4.0, (0.16, 0.30, 0.92, 0.52), "main_interface_map"),
    (38, 4.0, (0.16, 0.30, 0.56, 0.52), "left_module_box_and_flow"),
    (38, 4.0, (0.50, 0.30, 0.92, 0.52), "image_display_and_results"),
    # Quick toolbar / control toolbar pages
    (41, 3.0, (0.05, 0.05, 0.98, 0.95), "toolbar_page"),
    (42, 3.0, (0.05, 0.05, 0.98, 0.95), "menus_page"),
    (43, 3.0, (0.05, 0.05, 0.98, 0.95), "quick_toolbar_page"),
    # Image display area operations
    (44, 3.0, (0.10, 0.30, 0.95, 0.60), "display_settings_dialog"),
    # Flow configuration window (input / output / run / display tabs)
    (99, 3.0, (0.05, 0.05, 0.98, 0.95), "flow_config_input"),
    (103, 3.0, (0.05, 0.05, 0.98, 0.95), "module_common_config"),
]


def main() -> int:
    if not os.path.exists(DOC):
        print("external manual missing")
        return 1
    os.makedirs(OUT, exist_ok=True)
    pdf = pdfium.PdfDocument(DOC)

    for page_no, scale, (l, t, r, b), name in CROPS:
        page = pdf[page_no - 1]
        pil = page.render(scale=scale).to_pil()
        w, h = pil.size
        box = (int(w * l), int(h * t), int(w * r), int(h * b))
        crop = pil.crop(box)
        path = os.path.join(OUT, f"{name}.png")
        crop.save(path)
        print(f"saved {name}.png  {crop.size}  (page {page_no})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
