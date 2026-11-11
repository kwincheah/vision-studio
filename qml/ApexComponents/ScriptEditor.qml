import QtQuick 2.15
import ApexTheme 1.0

/*
 * A small code editor for module scripts.
 *
 * Layered so the text can be coloured without a C++ syntax highlighter: an editable
 * TextEdit draws the caret and takes the keys, and a read-only Text underneath paints the
 * same characters with syntax spans (HTML from `backend.highlightScript`, which uses
 * Python's own tokenizer).  Both use the same font and the same left padding, and neither
 * wraps, so the two stay aligned.
 *
 * What it gives a script author:
 *   line numbers · Python syntax colours · current-line highlight · auto-indent
 *   (including after ":") · Tab/Shift+Tab indent · Ctrl+/ comment toggle ·
 *   a syntax check that marks the offending line · Ln/Col readout · Ctrl+Enter to apply
 *
 *   ScriptEditor { text: "..."; onApplied: (source) => ... }
 */
Item {
    id: root
    property string text: ""
    property string hint: ""
    property bool readOnly: false
    signal applied(string source)
    signal edited(string source)

    implicitWidth: 420

    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    readonly property bool dirty: code.text !== text
    readonly property var check: backend ? backend.checkScript(code.text)
                                        : ({ ok: true, line: 0, message: "" })
    readonly property int errorLine: check.ok ? 0 : (check.line || 0)
    readonly property int lineCount: Math.max(1, code.text.split("\n").length)
    readonly property int currentLine: (function () {
        var upto = code.text.substring(0, code.cursorPosition)
        return upto.split("\n").length
    })()
    readonly property int currentColumn: (function () {
        var upto = code.text.substring(0, code.cursorPosition)
        var nl = upto.lastIndexOf("\n")
        return upto.length - nl
    })()

    // The exact height of one line in the editor's font: two lines, halved.
    TextMetrics {
        id: lineMetrics
        font.family: Theme.monoFamily
        font.pixelSize: Theme.fontBody
        text: "Xg\nXg"
    }
    readonly property real lineHeight: Math.max(1, lineMetrics.height / 2)

    // Inline colour map for the spans produced by core/script_highlight.
    readonly property string styleSheet:
        ".keyword{color:" + Theme.syntaxKeyword + "}" +
        ".builtin{color:" + Theme.syntaxBuiltin + "}" +
        ".string{color:" + Theme.syntaxString + "}" +
        ".number{color:" + Theme.syntaxNumber + "}" +
        ".comment{color:" + Theme.syntaxComment + ";font-style:italic}" +
        ".operator{color:" + Theme.syntaxOperator + "}" +
        ".def{color:" + Theme.syntaxDef + "}"

    function apply() {
        if (readOnly) return
        root.applied(code.text)
        root.text = code.text          // adopting it clears `dirty`
    }

    // ---- the edit surface -----------------------------------------------------------
    Rectangle {
        id: frame
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(90, root.height - 26)
        radius: Theme.radiusPanel
        color: Theme.fieldBg
        border.width: 1
        border.color: code.activeFocus
                      ? (root.errorLine > 0 ? Theme.editorErrorText : Theme.primary)
                      : (root.errorLine > 0 ? Theme.errorBorder : Theme.fieldBorder)

        // line-number gutter
        Rectangle {
            id: gutter
            width: Math.max(38, 10 + numberLabel.implicitWidth)
            height: parent.height
            radius: Theme.radiusPanel
            color: Theme.editorGutter
            // square off the right edge so only the outer corners stay rounded
            Rectangle {
                anchors.right: parent.right; anchors.top: parent.top
                anchors.bottom: parent.bottom; width: parent.radius
                color: parent.color
            }
            Text {
                id: numberLabel
                visible: false
                text: root.lineCount
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontBody
            }
            ListView {
                id: gutterList
                anchors.fill: parent
                anchors.topMargin: 8
                anchors.bottomMargin: 8
                interactive: false
                model: root.lineCount
                delegate: Item {
                    width: gutter.width; height: root.lineHeight
                    readonly property bool bad: (index + 1) === root.errorLine
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 6
                        text: index + 1
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.fontBody
                        font.weight: (index + 1) === root.currentLine ? Font.Bold : Font.Normal
                        color: parent.bad ? Theme.editorErrorText
                             : (index + 1) === root.currentLine ? Theme.textPrimary
                                                                : Theme.editorLineText
                    }
                }
            }
        }

        Flickable {
            id: flick
            objectName: "scriptFlick"
            anchors.left: gutter.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.margins: 8
            contentWidth: Math.max(code.contentWidth + 2 * code.leftPadding, width)
            contentHeight: Math.max(code.contentHeight + 2 * code.topPadding, height)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            // Scroll indicators drawn by hand: the application runs a native Controls
            // style, which refuses contentItem/background customisation (and draws its own
            // scrollbars near-black).
            Rectangle {
                id: vbar
                visible: flick.contentHeight > flick.height + 1
                width: 6; radius: 3
                color: Theme.fieldBorderHover
                anchors.right: parent.right
                anchors.rightMargin: 1
                height: Math.max(24, flick.height * flick.height / Math.max(1, flick.contentHeight))
                y: flick.contentY / Math.max(1, flick.contentHeight - flick.height)
                   * (flick.height - height)
            }
            Rectangle {
                id: hbar
                visible: flick.contentWidth > flick.width + 1
                height: 6; radius: 3
                color: Theme.fieldBorderHover
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 1
                width: Math.max(24, flick.width * flick.width / Math.max(1, flick.contentWidth))
                x: flick.contentX / Math.max(1, flick.contentWidth - flick.width)
                   * (flick.width - width)
            }

            // highlighted copy of the same text, drawn first
            Text {
                id: painted
                objectName: "scriptHighlight"
                x: code.leftPadding
                y: code.topPadding
                textFormat: Text.RichText
                text: root.backend
                      ? "<style>" + root.styleSheet + "</style>"
                        + root.backend.highlightScript(code.text)
                      : code.text
                wrapMode: Text.NoWrap
                font: code.font
                color: Theme.syntaxPlain
            }

            // the editor itself: transparent glyphs, visible caret and selection
            TextEdit {
                id: code
                objectName: "paramCode"
                width: Math.max(contentWidth, flick.width - 2 * leftPadding)
                leftPadding: 0
                topPadding: 0
                padding: 0
                wrapMode: TextEdit.NoWrap
                selectByMouse: true
                selectByKeyboard: true
                persistentSelection: true
                readOnly: root.readOnly
                activeFocusOnTab: !root.readOnly
                color: "transparent"
                selectionColor: Theme.primary
                selectedTextColor: "#ffffff"
                font.family: Theme.monoFamily
                font.pixelSize: Theme.fontBody
                cursorVisible: activeFocus
                text: root.text
                onTextChanged: root.edited(code.text)

                // ---- auto-indent, Tab, comment toggle ----
                Keys.onPressed: function (e) {
                    var pos = code.cursorPosition
                    var upto = code.text.substring(0, pos)
                    var lineStart = upto.lastIndexOf("\n") + 1
                    var indented = upto.substring(lineStart).match(/^[ \t]*/)[0]

                    if (e.key === Qt.Key_Tab) {
                        if (e.modifiers & Qt.ShiftModifier) {
                            // dedent the whole current line by up to 4 spaces
                            var lineText = code.text.substring(lineStart)
                            var strip = lineText.match(/^ {1,4}/)
                            if (strip) code.remove(lineStart, lineStart + strip[0].length)
                        } else {
                            code.insert(pos, "    ")
                        }
                        e.accepted = true
                    } else if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter)
                               && (e.modifiers & Qt.ControlModifier)) {
                        root.apply()
                        e.accepted = true
                    } else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                        // keep the indentation, and open a level after a ":"
                        var extra = /:\s*$/.test(upto.substring(lineStart)) ? "    " : ""
                        code.insert(pos, "\n" + indented + extra)
                        e.accepted = true
                    } else if (e.key === Qt.Key_Slash && (e.modifiers & Qt.ControlModifier)) {
                        // Ctrl+/ toggles a comment on the current line
                        var lineEnd = code.text.indexOf("\n", pos)
                        if (lineEnd < 0) lineEnd = code.text.length
                        var current = code.text.substring(lineStart, lineEnd)
                        if (/^\s*#/.test(current)) {
                            var hash = current.indexOf("#")
                            code.remove(lineStart + hash, lineStart + hash + 1)
                        } else {
                            code.insert(lineStart + indented.length, "#")
                        }
                        e.accepted = true
                    }
                }
            }
        }

        // keeps the caret's line visible while typing
        Connections {
            target: code
            function onCursorPositionChanged() {
                var y = code.cursorRectangle.y
                if (y < flick.contentY) flick.contentY = Math.max(0, y - 20)
                else if (y + code.cursorRectangle.height >
                         flick.contentY + flick.height) {
                    flick.contentY = y - flick.height + code.cursorRectangle.height + 20
                }
                gutterList.contentY = flick.contentY
            }
        }
        Connections {
            target: flick
            function onContentYChanged() { gutterList.contentY = flick.contentY }
        }
    }

    // ---- status bar -----------------------------------------------------------------
    Rectangle {
        id: bar
        anchors.top: frame.bottom
        anchors.topMargin: 4
        width: parent.width
        height: 22
        color: "transparent"

        Text {
            id: statusText
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: root.errorLine > 0
                  ? "\u25cf  " + root.check.message
                  : (root.dirty ? "\u25cf  Unsaved changes" : "\u2713  " + root.check.message)
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: root.errorLine > 0 ? Theme.editorErrorText
                 : root.dirty ? Theme.textSecondary : Theme.okText
            elide: Text.ElideRight
            width: parent.width - positionText.width - applyButton.width - 24
        }
        Text {
            id: positionText
            anchors.right: applyButton.left
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: "Ln " + root.currentLine + ", Col " + root.currentColumn
            font.family: Theme.monoFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
        }
        Row {
            id: applyButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            AppButton {
                objectName: "scriptApply"
                text: "Apply script"
                width: 104
                enabled: !root.readOnly && root.dirty
                onClicked: root.apply()
            }
        }
    }

    implicitHeight: 320
    onTextChanged: if (code.text !== text) code.text = text
}
