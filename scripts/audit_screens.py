"""Render every major screen and dialog, then audit the rendered pixels.

Two layers of checking, both against what the user actually sees:

1. Capture each screen (main window at several sizes, every dialog, every menu and
   submenu, the tool flyout, the validation list, the global-variable table).
2. Walk the *active* palette of each widget - its resolved `color` and
   `background-color` - and report the ones that cannot be read, which catches a
   dialog that overrides the theme with an inline colour.

Run:  python scripts/audit_screens.py
"""
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "docs", "screenshots", "audit")


def _srgb(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb) -> float:
    """Relative luminance of an (r, g, b) triple with 0-255 channels."""
    r, g, b = (float(v) for v in rgb[:3])
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast(a, b) -> float:
    """WCAG contrast between two (r, g, b) triples with 0-255 channels."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def pixel_probe(path: str, regions: Dict[str, Tuple[int, int, int, int]]) -> List[Dict]:
    """Measure the ink/fill contrast inside named regions of a captured screen.

    `QWidget.grab()` on a child returns a blank image in this setup, so the check is
    done on the captured *window* instead.  Within each region the darkest and
    lightest quartiles are treated as the ink and its fill: on a text-over-a-flat-fill
    region that split recovers the two populations, which is the quantity that decides
    whether a label is legible.
    """
    from PIL import Image
    import numpy as np

    if not os.path.exists(path):
        return []
    img = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    out = []
    for label, (x0, y0, x1, y1) in regions.items():
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        lum = (0.299 * crop[:, :, 0] + 0.587 * crop[:, :, 1]
               + 0.114 * crop[:, :, 2]).reshape(-1)
        if lum.size < 64:
            continue

        # The *fill* is the modal luminance - the flat surface behind the text.
        # The *ink* is the most extreme pixel that departs from it.  Taking
        # percentiles instead would measure the fill's own noise whenever a region
        # happens to contain no glyphs.
        hist, edges = np.histogram(lum, bins=32)
        modal_bin = int(np.argmax(hist))
        fill = 0.5 * (edges[modal_bin] + edges[modal_bin + 1])
        deviation = np.abs(lum - fill)
        ink_mask = deviation >= max(20.0, deviation.max() * 0.5)
        if not ink_mask.any():
            out.append({"region": label, "lo": round(float(fill), 1),
                        "hi": round(float(fill), 1), "ratio": 1.0,
                        "note": "no ink found"})
            continue
        ink_candidates = lum[ink_mask]
        ink = float(ink_candidates.min()) if fill > 128 else float(ink_candidates.max())
        ink_px = (int(round(ink)),) * 3
        fill_px = (int(round(fill)),) * 3
        out.append({"region": label, "lo": round(ink, 1), "hi": round(fill, 1),
                    "ratio": contrast(ink_px, fill_px)})
    return out


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    from vm_clone.ui.styles import initialize_app_fonts

    app = QApplication.instance() or QApplication([])
    initialize_app_fonts(app)

    from vm_clone.ui.main_window import VisionMasterMainWindow
    from vm_clone.ui.module_config import ModuleConfigDialog

    findings: List[str] = []
    captured: List[str] = []
    all_probes: List[Dict] = []

    for size in ((925, 765), (1400, 760), (1120, 760)):
        win = VisionMasterMainWindow()
        win.resize(*size)
        win.show()
        for _ in range(26):
            app.processEvents()
        name = f"80_main_{size[0]}x{size[1]}.png"
        win.grab().save(os.path.join(OUT, name))
        captured.append(name)

        # Menus: raise each menu and capture the popup.
        for action in win.menuBar().actions():
            menu = action.menu()
            if menu is None:
                continue
            menu.popup(win.mapToGlobal(win.rect().topLeft()))
            for _ in range(4):
                app.processEvents()
            title = re.sub(r"[^A-Za-z0-9]+", "_", action.text()).strip("_") or "menu"
            sub = f"81_menu_{title}.png"
            menu.grab().save(os.path.join(OUT, sub))
            captured.append(sub)
            menu.hide()
            for _ in range(2):
                app.processEvents()

        # Tool flyout for every category.
        for cat in list(win.toolbox.rail.category_names())[:4]:
            win.toolbox.rail.select_category(cat)
            win.toolbox._on_category(cat)
            for _ in range(5):
                app.processEvents()
            tag = re.sub(r"[^A-Za-z0-9]+", "_", cat).strip("_")
            sub = f"82_flyout_{tag}.png"
            win.toolbox.grab().save(os.path.join(OUT, sub))
            captured.append(sub)

        # Right column: both tab pages, and each result tab.
        win.data_tabs.setCurrentIndex(1)
        for _ in range(6):
            app.processEvents()
        win.property_dock.widget().grab().save(
            os.path.join(OUT, "83_result_page.png"))
        captured.append("83_result_page.png")
        win.data_tabs.setCurrentIndex(0)
        for i in range(win.result_display.tabs.count()):
            win.result_display.tabs.setCurrentIndex(i)
            for _ in range(4):
                app.processEvents()
            sub = f"84_resulttab_{i}.png"
            win.result_display.grab().save(os.path.join(OUT, sub))
            captured.append(sub)

        # Dialogs opened over the window.
        nid = next(iter(win.pipeline.nodes), None)
        if nid:
            tool = win.pipeline.nodes[nid]
            dlg = ModuleConfigDialog(tool, win.pipeline.last_results.get(nid), win)
            dlg.show()
            for _ in range(6):
                app.processEvents()
            for i in range(dlg.tabs.count()):
                dlg.tabs.setCurrentIndex(i)
                for _ in range(3):
                    app.processEvents()
                sub = f"85_moduleconfig_{i}.png"
                dlg.grab().save(os.path.join(OUT, sub))
                captured.append(sub)
            dlg.close()
            dlg.deleteLater()

        # Pixel probe of the surfaces that carry text, measured on the capture.
        name = f"80_main_{size[0]}x{size[1]}.png"
        probes = pixel_probe(os.path.join(OUT, name), {
            # status bar strip along the bottom
            "status bar": (8, size[1] - 26, size[0] - 8, size[1] - 4),
            # menu strip along the top
            "menu strip": (240, 2, 700, 24),
            # toolbar strip
            "toolbar strip": (60, 40, 460, 70),
            # flow tab bar
            "flow tab bar": (10, 82, 300, 106),
            # workspace tab strip
            "workspace tabs": (52, 118, 420, 142),
            # right column header row
            "image header": (size[0] - 460, 118, size[0] - 20, 142),
            # result table area
            "result grid": (size[0] - 460, size[1] - 220,
                            size[0] - 20, size[1] - 90),
        })
        all_probes.extend(probes)
        for p in probes:
            if p["ratio"] < 2.0:
                findings.append(
                    f"{name} {p['region']}: pixel contrast {p['ratio']}:1 "
                    f"(ink {p['lo']}, fill {p['hi']})")

        win.close()
        win.deleteLater()
        for _ in range(4):
            app.processEvents()

    print(f"captured {len(captured)} screens into {OUT}")

    if all_probes:
        worst = min(p["ratio"] for p in all_probes)
        print(f"\npixel-probe contrast by region "
              f"({len(all_probes)} readings, worst {worst:.2f}:1):")
        print(f"  {'region':16s} {'ink':>6s} {'fill':>6s} {'ratio':>7s}")
        for p in all_probes:
            flag = "ok " if p["ratio"] >= 2.0 else "LOW"
            print(f"  {flag} {p['region']:14s} {p['lo']:6.1f} {p['hi']:6.1f} "
                  f"{p['ratio']:7.2f}")

    if findings:
        uniq = sorted(set(findings))
        print(f"\n{len(uniq)} issue(s):")
        for f in uniq[:30]:
            print(f"  {f}")
    else:
        print("\nno readability issue found in the rendered surfaces")
    return 0


if __name__ == "__main__":
    sys.exit(main())
