"""Regenerate the SVG icon set used by the QML UI.

Each icon is written twice - ``images/light`` (for the dark steel chrome) and
``images/dark`` (for light panels) - because plain QML ``Image`` cannot recolour an SVG.
Run:  python qml/tools/make_icons.py
"""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "images"))
TONES = {"light": "#f0f2f4", "dark": "#1a2024", "accent": "#0078b0", "white": "#ffffff"}

#: name -> SVG body on a 24x24 canvas; ``{c}`` is the stroke colour
ICONS = {
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><path d="M8 20v-6h8v6"/>',
    "open": '<path d="M3 7h6l2 2h10v10H3z"/>',
    "folder": '<path d="M3 7h6l2 2h10v10H3z"/>',
    "image": '<rect x="4" y="5" width="16" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M5 18l5-5 3 3 3-3 3 3"/>',
    "undo": '<path d="M9 7L4 12l5 5"/><path d="M4 12h10a5 5 0 0 1 0 10h-2"/>',
    "redo": '<path d="M15 7l5 5-5 5"/><path d="M20 12H10a5 5 0 0 0 0 10h2"/>',
    "lock": '<rect x="6" y="11" width="12" height="9" rx="2"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>',
    "camera": '<rect x="3" y="7" width="13" height="10" rx="2"/><path d="M16 11l5-3v8l-5-3"/>',
    "table": '<rect x="4" y="5" width="16" height="14" rx="1"/><path d="M4 10h16M4 14.5h16M9.5 5v14"/>',
    "variable": '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 10l2 4 2-4M14 14h3"/>',
    "bolt": '<path d="M13 3L6 13h5l-1 8 8-11h-5z"/>',
    "script": '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M10 9l-3 3 3 3M14 9l3 3-3 3"/>',
    "run": '<path d="M8 5l11 7-11 7z" fill="{c}"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="1.5" fill="{c}"/>',
    "loop": '<path d="M5 12a7 7 0 0 1 12-5l2 2"/><path d="M19 4v5h-5"/><path d="M19 12a7 7 0 0 1-12 5l-2-2"/><path d="M5 20v-5h5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "user": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-4.5 13.2-4.5 14 0"/>',
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "layers": '<path d="M12 4l9 5-9 5-9-5z"/><path d="M3 14l9 5 9-5"/>',
    "histogram": '<path d="M5 20V12M10 20V6M15 20V10M20 20V14"/>',
    "roi": '<rect x="5" y="5" width="14" height="14" stroke-dasharray="3 2"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M16 16l4 4"/>',
    "target": '<circle cx="12" cy="12" r="7"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/>',
    "measure": '<path d="M4 8v8M20 8v8M4 12h16M8 10v4M16 10v4"/>',
    "shield": '<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/><path d="M12 8v5M12 16v.5"/>',
    "grid": '<rect x="4" y="4" width="16" height="16"/><path d="M4 9.3h16M4 14.7h16M9.3 4v16M14.7 4v16"/>',
    "logic": '<path d="M5 6h4l3 6-3 6H5"/><path d="M12 12h7"/>',
    "comm": '<path d="M5 8h14M5 12h14M5 16h9"/>',
    "list": '<path d="M5 7h14M5 12h14M5 17h14"/>',
    "palette": '<circle cx="9" cy="10" r="3"/><circle cx="15" cy="10" r="3"/><circle cx="12" cy="15" r="3"/>',
    "text": '<path d="M5 6h14M12 6v13M9 19h6"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "send": '<path d="M4 12l16-8-6 16-3-7z"/>',
    "key": '<circle cx="8" cy="15" r="3.5"/><path d="M10.5 12.5L19 4M16 7l3 3"/>',
    "copy": '<rect x="8" y="8" width="11" height="12" rx="2"/><path d="M5 16V6a2 2 0 0 1 2-2h8"/>',
    "download": '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>',
    "trash": '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>',
}


def main() -> None:
    for tone, colour in TONES.items():
        folder = os.path.join(ROOT, tone)
        os.makedirs(folder, exist_ok=True)
        for name, body in ICONS.items():
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
                f'fill="none" stroke="{colour}" stroke-width="1.7" stroke-linecap="round" '
                f'stroke-linejoin="round">{body.replace("{c}", colour)}</svg>\n'
            )
            with open(os.path.join(folder, f"{name}.svg"), "w", encoding="utf-8") as fh:
                fh.write(svg)
    print(f"wrote {len(ICONS)} icons x {len(TONES)} tones to {ROOT}")


if __name__ == "__main__":
    main()
