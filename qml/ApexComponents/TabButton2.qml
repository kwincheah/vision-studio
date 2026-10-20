import QtQuick 2.15
import ApexTheme 1.0

// Flat tab used by the workspace tabs (Flow Diagram | Operation Interface | Multi-Flow) and the
// right-column tabs.  "light" tabs sit on a panel, "dark" tabs on the chrome strip.
Rectangle {
    id: root
    property string text: "Tab"
    property bool selected: false
    signal clicked()

    implicitHeight: 26
    implicitWidth: label.implicitWidth + 2 * Theme.spLoose + 4
    color: selected ? Theme.panelAlt : mouse.containsMouse ? Theme.panelHeader : "#dfe3e6"
    border.width: 1
    border.color: "#c0c4c8"

    Rectangle {          // amber underline on the selected tab
        visible: root.selected
        anchors.top: parent.top
        width: parent.width
        height: 2
        color: Theme.accent
    }
    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        font.weight: root.selected ? Font.DemiBold : Font.Normal
        color: root.selected ? Theme.textPrimary : Theme.textSecondary
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
