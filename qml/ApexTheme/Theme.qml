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
    readonly property color primaryHover: "#0a89c4"
    readonly property color wire: "#005f8c"

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
    readonly property color runGreen: "#15803d"
    readonly property color runGreenHover: "#16a34a"
    readonly property color stopRed: "#b91c1c"
    readonly property color stopRedHover: "#dc2626"

    // ---- type --------------------------------------------------------------------
    readonly property string fontFamily: "Segoe UI"
    readonly property string monoFamily: "Consolas"
    readonly property int fontMicro: 11
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
