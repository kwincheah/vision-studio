"""Check text/background contrast in the QML interface.

The widget UI has a contrast guard; the QML port of the palette does not.  This resolves
the `Theme.*` colour names used in QML, pairs each text colour with the surface it is
drawn on, and reports anything below the WCAG AA threshold for its size.

Run:  python scripts/audit_qml_contrast.py [--strict]
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, "qml", "ApexTheme", "Theme.qml")


def load_theme() -> dict:
    colours = {}
    text = open(THEME, encoding="utf-8").read()
    for m in re.finditer(r'readonly property color (\w+)\s*:\s*"(#[0-9a-fA-F]{6})"', text):
        colours[m.group(1)] = m.group(2).lower()
    return colours


def srgb(channel: float) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def code_only(text: str) -> str:
    """Strip `//` comments so a literal quoted in a note is not read as code."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())


#: The pairs that actually co-occur, named so a failure says where to look.
#:
#: These were read out of the QML rather than assumed.  The menu bar, for instance, draws
#: `textPrimary` on the light `chrome` strip, not `textOnChrome` - an earlier version of
#: this script paired the wrong ink and reported a false failure at 3.04:1.
PAIRS = [
    # (foreground token, background token, where, size in px)
    ("textPrimary", "chrome", "menu bar (dark ink on the light strip)", 12),
    ("textOnChrome", "chromeDark", "toolbars, status bar", 12),
    ("textOnChrome", "rail", "tool rail", 12),
    ("textPrimary", "panel", "panels", 13),
    ("textPrimary", "panelAlt", "alternate panels", 13),
    ("textPrimary", "card", "node cards", 12),
    ("textPrimary", "fieldBg", "fields", 12),
    ("textPrimary", "panelHeader", "panel headers", 11),
    ("textPrimary", "buttonBg", "buttons", 12),
    ("textPrimary", "buttonHover", "hovered buttons", 12),
    ("textSecondary", "panel", "secondary labels on panels", 11),
    ("textSecondary", "card", "secondary labels on cards", 11),
    ("textSecondary", "buttonBg", "button labels", 12),
    ("textSecondary", "panelAlt", "secondary labels on alternate panels", 11),
    ("textMuted", "panel", "muted labels on panels", 11),
    ("textMuted", "panelAlt", "muted labels on alternate panels", 11),
    ("textMuted", "card", "muted labels on cards", 11),
    ("viewportText", "viewport", "image viewport overlay", 11),
    ("okText", "okBg", "PASS badge", 11),
    ("errorText", "errorBg", "FAIL badge", 11),
    ("warnText", "warnBg", "warning badge", 11),
    ("primaryText", "panel", "primary-coloured text", 12),
    ("canvasDot", "canvas", "grid dots on the canvas", 1),
]

#: Filled buttons put white on a saturated fill; these are the fills.
FILLED = [
    ("#ffffff", "runGreen", "AppButton kind=run", 12),
    ("#ffffff", "runGreenHover", "AppButton kind=run hovered", 12),
    ("#ffffff", "stopRed", "AppButton kind=stop", 12),
    ("#ffffff", "stopRedHover", "AppButton kind=stop hovered", 12),
    ("#ffffff", "primary", "AppButton kind=primary", 12),
    ("#ffffff", "primaryHover", "AppButton kind=primary hovered", 12),
    ("#ffffff", "okBorder", "StatusBadge kind=ok (PASS)", 11),
    ("#ffffff", "errorBorder", "StatusBadge kind=error (FAIL)", 11),
    ("#ffffff", "warnText", "StatusBadge kind=warn", 11),
]

#: Deliberate low-contrast relationships, with the reason, mirroring the widget guard.
APPROVED = {
    ("canvasDot", "canvas"): "a grid dot is a texture, never information",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    theme = load_theme()
    print(f"{len(theme)} colour tokens in Theme.qml\n")

    bad = []
    for fg, bg, where, size in PAIRS:
        if fg not in theme or bg not in theme:
            if bg == "deviation":
                continue
            print(f"  SKIP  {fg} on {bg}: token missing")
            continue
        ratio = contrast(theme[fg], theme[bg])
        need = 3.0 if size >= 18 else 4.5
        ok = ratio >= need or (fg, bg) in APPROVED
        mark = "ok  " if ok else "FAIL"
        print(f"  {mark}  {ratio:5.2f}:1  (need {need:.1f})  "
              f"{fg} on {bg:14s} {where}")
        if not ok:
            bad.append((fg, bg, where, ratio, need))

    # Also report any text colour used on `chrome`/`chromeDark` that is not the light ink:
    # the dark-ink-on-dark-chrome mistake this palette avoids in the widget UI.
    # Also check the filled buttons: white text on a saturated fill is where a palette
    # most often slips below AA, because the fill is chosen for its hue, not its lightness.
    for fg, bg, where, size in FILLED:
        if bg not in theme:
            print(f"  SKIP  {bg}: token missing")
            continue
        ratio = contrast(fg, theme[bg])
        need = 3.0 if size >= 18 else 4.5
        ok = ratio >= need
        print(f"  {'ok  ' if ok else 'FAIL'}  {ratio:5.2f}:1  (need {need:.1f})  "
              f"white on {bg:16s} {where}")
        if not ok:
            bad.append((bg, bg, where, ratio, need))

    # --- verify the ink/background pair actually used inside each chrome strip --------
    # A file-level heuristic ("dark inks appear in a file that mentions chromeDark") is
    # useless - menus and dialogs live in the same file.  This extracts each strip's own
    # block by brace matching and checks the text colours declared inside it.
    print("\nchrome strips: the ink actually used")
    ink_ok = True
    strips = (
        # (id in the QML, the token its background uses)
        ("menuBar", "chrome"),
        ("toolbar1", "chromeDark"),
        ("toolbar2", "chromeDark"),
        ("statusBar", "chromeDark"),
    )
    source = code_only(open(os.path.join(ROOT, "qml", "screens", "MainScreen.qml"),
                            encoding="utf-8").read())
    for strip, fill in strips:
        block = extract_block(source, f"id: {strip}")
        if block is None:
            print(f"  SKIP  {strip}: block not found")
            continue
        inks = {t.split(".", 1)[-1] for t in colours_in(block)
                if t.startswith("Theme.")}
        # only the text inks matter; a literal here is a fill for an icon button
        inks = {i for i in inks if i in theme and i.startswith("text")}
        if not inks:
            print(f"  SKIP  {strip}: no text token")
            continue
        worst = min(inks, key=lambda i: contrast(theme[i], theme[fill]))
        ratio = contrast(theme[worst], theme[fill])
        ok = ratio >= 4.5
        ink_ok = ink_ok and ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {strip:10s} on {fill:11s} "
              f"ink={sorted(inks)}  worst {worst} = {ratio:.2f}:1")
        if not ok:
            bad.append((worst, fill, f"{strip} text ink", ratio, 4.5))

    print()
    if bad:
        print(f"{len(bad)} pair(s) below target:")
        for fg, bg, where, ratio, need in bad:
            print(f"  {fg} on {bg} ({where}) = {ratio:.2f}:1, need {need:.1f}")
        if args.strict:
            return 1
    else:
        print("every pair meets its target")
    return 0 if ink_ok else (1 if args.strict else 0)


def extract_block(text: str, marker: str):
    """The `{...}` block containing `marker`, found by brace depth."""
    at = text.find(marker)
    if at == -1:
        return None
    start = text.rfind("{", 0, at)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def colours_in(block: str):
    return re.findall(r"color:\s*(Theme\.\w+|\"#[0-9a-fA-F]{6,8}\")", block or "")


if __name__ == "__main__":
    sys.exit(main())
