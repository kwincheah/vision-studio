"""Side-by-side reference/implementation comparison with measured deviations.

Captures the application at the reference window size (925x765, the size of the
bundled manual's uncropped Home Page figure), renders a comparison sheet against
the vendor crops, prints the measured layout deviations, and writes both the
sheet and the metric table to `docs/references/external/`.

Run:  python scripts/compare_layout.py
"""
import json
import os
import sys
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

SHOTS = os.path.join(ROOT, "docs", "screenshots")
AUDIT = os.path.join(SHOTS, "audit")
EXT = os.path.join(ROOT, "docs", "references", "external")
FIGS = os.path.join(ROOT, "docs", "references", "figs")
OUT_JSON = os.path.join(EXT, "layout_deviations.json")

REF_HOME = os.path.join(FIGS, "p040_01.png")
REF_RIGHT = os.path.join(EXT, "ui_crops", "right_column_zoom.png")
REF_CARDS = os.path.join(EXT, "ui_crops", "card_zoom.png")


def capture() -> Tuple[str, Dict]:
    """Render the app at the reference size and return the measured geometry."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    from PyQt6.QtWidgets import QApplication
    from vm_clone.ui.styles import initialize_app_fonts
    from vm_clone.ui.main_window import VisionMasterMainWindow
    from vm_clone.ui import layout_metrics as LM

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    win = VisionMasterMainWindow()
    win.resize(*LM.REF_WINDOW)
    win.show()
    for _ in range(30):
        app.processEvents()

    path = os.path.join(AUDIT, "40_reference_size_layout.png")
    win.grab().save(path)
    # Also capture just the right column, for the detail comparison.
    detail = os.path.join(AUDIT, "41_right_column_detail.png")
    win.property_dock.widget().grab().save(detail)

    total = (win.tool_dock.width() + win.centralWidget().width()
             + win.property_dock.width())
    chrome = (win.menuBar().height() + win.toolbar_resources.height()
              + win.toolbar_flows.height())
    content_h = chrome + win.centralWidget().height()
    sizes = win.split_right.sizes()
    # The image and result blocks are bands *of the right column*, so their shares
    # are measured against the column's own height - the same basis the reference
    # bands were measured on - not against the whole window.
    column_h = sum(sizes)

    metrics = {
        "window": [win.width(), win.height()],
        "content_w": total,
        "content_h": content_h,
        "right_column_h": column_h,
        "rail_w": win.tool_dock.width(),
        "canvas_w": win.centralWidget().width(),
        "right_w": win.property_dock.width(),
        "rail_ratio": round(win.tool_dock.width() / total, 4),
        "canvas_ratio": round(win.centralWidget().width() / total, 4),
        "right_ratio": round(win.property_dock.width() / total, 4),
        "chrome_h": chrome,
        "chrome_ratio": round(chrome / content_h, 4),
        "image_block_h": sizes[0],
        "image_block_ratio": round(sizes[0] / column_h, 4),
        "result_block_h": sizes[1],
        "result_block_ratio": round(sizes[1] / column_h, 4),
    }
    win.close()
    return path, metrics


def deviations(metrics: Dict) -> List[Dict]:
    from vm_clone.ui import layout_metrics as LM
    rows = [
        ("rail width", metrics["rail_ratio"], LM.REF_COLUMN_RATIOS["rail"]),
        ("canvas width", metrics["canvas_ratio"], LM.REF_COLUMN_RATIOS["canvas"]),
        ("right column width", metrics["right_ratio"], LM.REF_COLUMN_RATIOS["right"]),
        ("chrome height", metrics["chrome_ratio"], LM.CHROME_RATIO),
        ("image block height", metrics["image_block_ratio"],
         LM.IMAGE_BLOCK_RATIO_REFERENCE),
        ("result block height", metrics["result_block_ratio"],
         LM.RESULT_BLOCK_RATIO_REFERENCE),
    ]
    out = []
    for name, got, ref in rows:
        out.append({"measure": name, "reference": round(ref, 4),
                    "applied": round(got, 4), "delta": round(got - ref, 4)})
    return out


def sheet(pairs: List[Tuple[str, str]], out_name: str, cell_h: int = 330) -> str:
    imgs = []
    for label, path in pairs:
        if not os.path.exists(path):
            print(f"  missing {path}")
            continue
        im = Image.open(path).convert("RGB")
        scale = cell_h / im.height
        imgs.append((label, im.resize((max(1, int(im.width * scale)), cell_h),
                                      Image.LANCZOS)))
    if not imgs:
        return ""
    cols = 2
    rows = (len(imgs) + cols - 1) // cols
    pad, label_h = 10, 18
    cell_w = max(im.width for _, im in imgs)
    width = cols * cell_w + (cols + 1) * pad
    height = rows * (cell_h + label_h) + (rows + 1) * pad

    canvas = Image.new("RGB", (width, height), (24, 24, 28))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("segoeui.ttf", 12)
    except Exception:
        font = ImageFont.load_default()

    for idx, (label, im) in enumerate(imgs):
        r, c = divmod(idx, cols)
        x = pad + c * (cell_w + pad)
        y = pad + r * (cell_h + label_h + pad)
        draw.text((x, y), label, fill=(230, 230, 235), font=font)
        canvas.paste(im, (x, y + label_h))
    path = os.path.join(SHOTS, out_name)
    canvas.save(path)
    print(f"saved {path}  ({canvas.width}x{canvas.height})")
    return path


def main() -> int:
    capture_path, metrics = capture()

    pairs = [
        ("REFERENCE - Home Page, uncropped window (925x765)  [manual fig. p.40]",
         REF_HOME),
        ("IMPLEMENTATION - captured at the same 925x765  [40_reference_size_layout]",
         capture_path),
        ("REFERENCE - right column at 2x  [ui_crops/right_column_zoom]",
         REF_RIGHT),
        ("IMPLEMENTATION - right column  [41_right_column_detail]",
         os.path.join(AUDIT, "41_right_column_detail.png")),
        ("REFERENCE - module cards  [ui_crops/card_zoom]",
         REF_CARDS),
        ("IMPLEMENTATION - workspace  [docs/screenshots/vm_flow_workspace]",
         os.path.join(SHOTS, "vm_flow_workspace.png")),
    ]
    sheet(pairs, "layout_comparison.png", cell_h=330)

    rows = deviations(metrics)
    print("\n=== MEASURED LAYOUT DEVIATIONS ===")
    print(f"window {metrics['window']}  content {metrics['content_w']}x"
          f"{metrics['content_h']}")
    print(f"{'measure':22s} {'reference':>10s} {'applied':>10s} {'delta':>9s}")
    for row in rows:
        print(f"{row['measure']:22s} {row['reference']:10.4f} "
              f"{row['applied']:10.4f} {row['delta']:+9.4f}")

    worst = max((abs(r["delta"]) for r in rows), default=0.0)
    print(f"\nworst deviation: {worst:.4f}")

    payload = {"metrics": metrics, "deviations": rows,
               "worst_deviation": round(worst, 4)}
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    print(f"wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
