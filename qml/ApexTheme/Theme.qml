pragma Singleton
import QtQuick 2.15

/*
 * Design tokens for Apex Industrial Vision Studio.
 * Mirrors apex_vision/ui/theme.py (the widget UI) - change a value here and every
 * component and screen follows.
 */
QtObject {
    // ---- chrome (menu bar, toolbars, rail, status bar) ---------------------------
    readonly property color chrome: "#848c94"
    readonly property color chromeDark: "#646c6c"
    readonly property color rail: "#505854"
    readonly property color railHover: "#6a7270"
    readonly property color chromeOutline: "#6a727a"
    readonly property color chromeHover: "#98a0a7"
    readonly property color textOnChrome: "#f0f2f4"

    // ---- panels and canvas -------------------------------------------------------
    readonly property color appBg: "#e4e7ea"
    readonly property color panel: "#ecf0f0"
    readonly property color panelAlt: "#f8fafb"
    readonly property color panelHeader: "#d8dcdf"
    readonly property color canvas: "#b4b8c0"
    readonly property color canvasDot: "#949aa4"
    readonly property color viewport: "#201c20"
    readonly property color viewportText: "#e8eaec"
    readonly property color card: "#fcfcfc"

    // ---- ink ---------------------------------------------------------------------
    readonly property color textPrimary: "#1a2024"
    readonly property color textSecondary: "#414850"
    readonly property color textMuted: "#515960"

    // ---- accents -----------------------------------------------------------------
    readonly property color accent: "#e4b030"          // amber selection
    readonly property color accentHover: "#f0c050"
    readonly property color accentDim: "#f8e8c8"
    readonly property color accentBorder: "#6f4a04"
    readonly property color primaryText: "#005f8c"      // primary-coloured text on light panels (AA contrast)
    readonly property color primary: "#0078b0"         // default actions, focus
    // Focus on the dark chrome cannot use `primary`: blue on #646c6c is 1.11:1, i.e. an
    // invisible ring.  Chrome surfaces take this light ring instead (4.79:1 on chromeDark,
    // 6.53:1 on the rail).  On the light menu strip (chrome, #848c94) even white only
    // reaches 3.41:1, which clears the 3:1 non-text target.
    readonly property color focusOnChrome: "#ffffff"
    readonly property color primaryHover: "#00719f"     // white text 5.44:1 (was #0a89c4, 3.90:1)
    readonly property color wire: "#005f8c"
    // A hairline divider between toolbar groups.  It was the literal "#8a9290" repeated in
    // two places; at 3.4:1 against chromeDark it clears the 3:1 non-text target.
    readonly property color chromeDivider: "#8a9290"
    // A wire port that is a valid drop target while dragging.
    readonly property color portHot: "#22c55e"

    // ---- inputs ------------------------------------------------------------------
    readonly property color fieldBg: "#ffffff"
    readonly property color fieldBorder: "#aab3b9"
    readonly property color fieldBorderHover: "#7d8991"
    readonly property color buttonBg: "#f6f8f9"
    readonly property color buttonHover: "#e8edf0"
    readonly property color buttonPressed: "#d8dfe3"

    // ---- status ------------------------------------------------------------------
    readonly property color okText: "#076b3a"
    readonly property color okBg: "#d8f0e2"
    readonly property color okBorder: "#00754a"
    readonly property color errorText: "#b81c20"
    readonly property color errorBg: "#fadadd"
    readonly property color errorBorder: "#c8161a"
    readonly property color warnText: "#8a5a0e"
    readonly property color warnBg: "#fbeccf"
    readonly property color runGreen: "#15803d"          // white text 5.02:1
    // Hover used to lighten past AA (#16a34a = 3.30:1 with white).  It now lightens only
    // as far as the threshold allows, so the affordance survives and the label stays legible.
    readonly property color runGreenHover: "#1c7a3f"     // white text 5.38:1
    readonly property color stopRed: "#b91c1c"           // white text 6.47:1
    readonly property color stopRedHover: "#dc2626"      // white text 4.83:1
    // Dark filled variants for the chrome strips: the glyph is light, so the fill must be
    // dark enough for it to read.  These were four hex literals inside ChromeToolButton.
    readonly property color runFillDark: "#15351f"        // light glyph 11.99:1
    readonly property color runFillDarkHover: "#1d4d2e"   // light glyph 8.69:1
    readonly property color stopFillDark: "#3b181c"       // light glyph 14.03:1
    readonly property color stopFillDarkHover: "#5a242a"  // light glyph 10.88:1

    // ---- type --------------------------------------------------------------------
    readonly property string fontFamily: "Segoe UI"
    readonly property string monoFamily: "Consolas"

    // ---- script editor -------------------------------------------------------------
    // Syntax colours, measured against the editor's white well (`fieldBg`, #ffffff) so
    // every token clears AA even though code is read in dense bursts.
    readonly property color syntaxKeyword: "#005f8c"    // def / return / if      6.96:1
    readonly property color syntaxBuiltin: "#7a3e9d"    // print / len / int      6.99:1
    readonly property color syntaxString: "#0a6b3d"     // 'text'                 6.60:1
    readonly property color syntaxNumber: "#a4501a"     // 42 / 3.14              5.61:1
    readonly property color syntaxComment: "#6b7478"    // # note                 4.78:1
    readonly property color syntaxOperator: "#3c4247"   // + - = ==              10.18:1
    readonly property color syntaxDef: "#123d63"        // a defined name        11.21:1
    readonly property color syntaxPlain: "#1b2024"      // ordinary text         16.42:1
    readonly property color editorGutter: "#f2f4f5"     // line-number column
    readonly property color editorLineText: "#7c868c"   // line numbers           3.37:1
    readonly property color editorCurrentLine: "#f4f7f9"  // the caret's line
    readonly property color editorErrorLine: "#fbe9ea"  // a line the compiler rejects
    readonly property color editorErrorText: "#8f1d23"
    readonly property int fontCaption: 11
    readonly property int fontBody: 12
    readonly property int fontLabel: 13
    readonly property int fontSubtitle: 14
    readonly property int fontTitle: 16

    // ---- spacing, radii, heights -------------------------------------------------
    readonly property int spHair: 2
    readonly property int spTight: 4
    readonly property int spSnug: 6
    readonly property int spBase: 8
    readonly property int spLoose: 12
    readonly property int spSection: 16
    readonly property int radiusControl: 3
    readonly property int radiusPanel: 4
    readonly property int heightControl: 24
    readonly property int heightButton: 26
    readonly property int heightMenuBar: 31
    readonly property int heightToolbar: 42
    readonly property int heightTabBar: 34
    readonly property int railWidth: 42
    readonly property int statusBarHeight: 24

    // ---- data-type colours: ports and the wires leaving them share one colour per type ---------
    function portColor(dtype, kind) {
        switch (dtype) {
        case "IMAGE": return "#2b7bb9"
        case "VALUE": case "BOOLEAN": return "#e4a020"
        case "STRING": return "#8a5bd0"
        case "POINT": return "#d6537a"
        case "LINE": return "#17a2b8"
        case "CIRCLE": return "#7cb342"
        case "REGION": return "#2f9e5a"
        case "ANY": case "DICT": return "#6b7780"
        }
        return kind === "image" ? "#2b7bb9" : kind === "value" ? "#e4a020" : kind === "string" ? "#8a5bd0" : "#2f9e5a"
    }
}
