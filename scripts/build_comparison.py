"""Build a side-by-side before/after comparison sheet.

Combines the pre-redesign workspace snapshot with the VisionMaster-aligned
result so the visual delta is measurable, and overlays a reference figure
extracted from the official manual for direct comparison.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SHOTS = os.path.join(ROOT, "docs", "screenshots")
REFS = os.path.join(ROOT, "docs", "references", "figs")
EXT = os.path.join(ROOT, "docs", "references", "external")

LABEL_H = 30
GAP = 16
BG = (24, 24, 28)
FG = (232, 234, 238)


def _font(size: int):
    for candidate in ("segoeui.ttf", "arial.ttf"):
        path = os.path.join("C:\\Windows\\Fonts", candidate)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def load(path: str, height: int) -> Image.Image:
    img = Image.open(path).convert("RGB")
    scale = height / img.height
    return img.resize((max(1, int(img.width * scale)), height), Image.LANCZOS)


def build(rows, out_name: str, cell_h: int = 300):
    panels = []
    for title, path in rows:
        if not os.path.exists(path):
            print(f"  skip (missing): {path}")
            continue
        panels.append((title, load(path, cell_h)))

    if not panels:
        raise SystemExit("no panels to render")

    cols = 3
    rows_n = (len(panels) + cols - 1) // cols
    col_w = max(p.width for _, p in panels)
    sheet_w = cols * col_w + (cols + 1) * GAP
    sheet_h = rows_n * (cell_h + LABEL_H) + (rows_n + 1) * GAP

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    font = _font(15)

    for idx, (title, img) in enumerate(panels):
        r, c = divmod(idx, cols)
        x = GAP + c * (col_w + GAP) + (col_w - img.width) // 2
        y = GAP + r * (cell_h + LABEL_H + GAP)
        # Truncate long labels to the panel width so captions never collide.
        label = title
        while draw.textlength(label, font=font) > col_w - 8 and len(label) > 12:
            label = label[:-2]
        if label != title:
            label = label.rstrip(" -") + " ..."
        draw.text((x, y + 6), label, fill=FG, font=font)
        sheet.paste(img, (x, y + LABEL_H))

    out = os.path.join(SHOTS, out_name)
    sheet.save(out)
    print(f"saved {out}  ({sheet.width}x{sheet.height})")


def main() -> int:
    build(
        [
            ("BEFORE - original workspace (1500x950)",
             os.path.join(SHOTS, "before_workspace.png")),
            ("REFERENCE - tool grid / module cards (manual p.74)",
             os.path.join(REFS, "p074_01.png")),
            ("AFTER - Flow Diagram workspace (1600x950)",
             os.path.join(SHOTS, "vm_flow_workspace.png")),
            ("REFERENCE - Home page layout (manual p.40)",
             os.path.join(REFS, "p040_01.png")),
            ("REFERENCE - Result grid columns (manual p.87)",
             os.path.join(REFS, "p087_01.png")),
            ("AFTER - Result panel (Param / Current Result / Global Var)",
             os.path.join(SHOTS, "vm_result_panel.png")),
            ("REFERENCE - Multi-flow overview (manual p.95)",
             os.path.join(REFS, "p095_01.png")),
            ("AFTER - Multi-Flow overview",
             os.path.join(SHOTS, "vm_multiflow_overview.png")),
            ("AFTER - Tool Box rail + flyout grid",
             os.path.join(SHOTS, "vm_toolbox_flyout.png")),
        ],
        "comparison_sheet.png",
    )

    build(
        [
            ("REFERENCE - category rail + module cards (manual p.72/p.74)",
             os.path.join(REFS, "p074_01.png")),
            ("AFTER - Tool Box close-up (rail + flyout grid)",
             os.path.join(SHOTS, "vm_toolbox_closeup.png")),
            ("BEFORE - original Tool Library tree",
             os.path.join(SHOTS, "before_workspace.png")),
        ],
        "toolbox_comparison.png",
        cell_h=420,
    )
    # Audit sheet: reference figure next to the implemented screen it pins down.
    build(
        [
            ("REFERENCE - Home page layout (manual p.40)",
             os.path.join(REFS, "p040_01.png")),
            ("AFTER - main workspace, two control rows + status-bar message",
             os.path.join(SHOTS, "vm_flow_workspace.png")),
            ("REFERENCE - Result grid columns (manual p.87)",
             os.path.join(REFS, "p087_01.png")),
            ("AFTER - Result grid: Param Name / Current Result / Global Var.",
             os.path.join(SHOTS, "audit", "04_result_panel.png")),
            ("REFERENCE - Multi-flow overview (manual p.95)",
             os.path.join(REFS, "p095_01.png")),
            ("AFTER - Multi-Flow overview",
             os.path.join(SHOTS, "vm_multiflow_overview.png")),
            ("REFERENCE - category rail + module cards (manual p.72/p.74)",
             os.path.join(REFS, "p074_01.png")),
            ("AFTER - Tool Box rail + flyout grid",
             os.path.join(SHOTS, "vm_toolbox_flyout.png")),
            ("AFTER - 1100x720 minimum size, nothing clipped",
             os.path.join(SHOTS, "audit", "13_small_window.png")),
        ],
        "audit_comparison.png",
        cell_h=290,
    )
    # Reference-spec sheet: vendor annotated region map vs the implementation.
    build(
        [
            ("REFERENCE - annotated main interface, 13 regions (manual 4.3.0 Fig. 5-2)",
             os.path.join(EXT, "ui_crops", "main_interface_map.png")),
            ("AFTER - reproduced workspace",
             os.path.join(SHOTS, "vm_flow_workspace.png")),
            ("REFERENCE - right column: Image|Module Results over Current|History|Help",
             os.path.join(EXT, "ui_crops", "right_column_zoom.png")),
            ("AFTER - reproduced right column (same two tab bars)",
             os.path.join(SHOTS, "audit", "26_right_column_closeup.png")),
            ("REFERENCE - image display area + result table (regions 6/12)",
             os.path.join(EXT, "ui_crops", "image_display_and_results.png")),
            ("AFTER - image display area + result table",
             os.path.join(SHOTS, "audit", "23_image_display.png")),
            ("REFERENCE - module config dialog, run params tab (manual Fig. 8-16)",
             os.path.join(EXT, "ui_crops", "module_common_config.png")),
            ("AFTER - module configuration window (Run Params tab)",
             os.path.join(SHOTS, "audit", "22_module_config_tab2.png")),
            ("REFERENCE - module box rail + flow cards (manual Fig. 5-2)",
             os.path.join(EXT, "ui_crops", "left_module_box_and_flow.png")),
            ("AFTER - flow canvas: card badges, wires, zoom tool, probe",
             os.path.join(SHOTS, "audit", "25_vm_right_column.png")),
            ("AFTER - live window after a shrink-resize (docks rebalanced)",
             os.path.join(SHOTS, "live_window_small.png")),
            ("AFTER - 1100x720 minimum size",
             os.path.join(SHOTS, "audit", "13_small_window.png")),
        ],
        "spec_comparison.png",
        cell_h=300,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
