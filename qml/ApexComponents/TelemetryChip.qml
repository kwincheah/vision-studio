import QtQuick 2.15
import ApexTheme 1.0

// Small read-out chip under the flow canvas ("Flow: 152.74ms").  emphasis gives the amber edge.
Rectangle {
    id: root
    property string text: "Tools: 7"
    property bool emphasis: false

    implicitHeight: 22
    implicitWidth: label.implicitWidth + 2 * Theme.spBase + 8
    radius: Theme.radiusPanel
    color: Theme.panelAlt
    border.width: 1
    border.color: emphasis ? Theme.accentBorder : Theme.fieldBorder

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        font.weight: root.emphasis ? Font.DemiBold : Font.Normal
        color: root.emphasis ? Theme.textPrimary : Theme.textSecondary
    }
}
