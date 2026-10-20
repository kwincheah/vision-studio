import QtQuick 2.15
import ApexTheme 1.0

// Overall verdict badge: solid fill, white text.  kind = "ok" | "error" | "warn" | "run";
// both the fill and the text follow `kind` / `text`, so they always show the real verdict.
Rectangle {
    id: root
    property string text: "PASS"
    property string kind: "ok"

    implicitWidth: label.implicitWidth + 2 * Theme.spLoose + 8
    implicitHeight: 30
    radius: Theme.radiusPanel
    color: kind === "ok" ? "#00754a" : kind === "error" ? "#c8161a" : kind === "warn" ? Theme.warnText : Theme.primary
    border.width: 1
    border.color: kind === "ok" ? Theme.okBorder : kind === "error" ? Theme.errorBorder : kind === "warn" ? Theme.warnText : "#00638f"

    Text {
        id: label
        color: "#ffffff"
        anchors.centerIn: parent
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        font.weight: Font.Bold
        text: root.text
    }
}
