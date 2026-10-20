import QtQuick 2.15
import ApexTheme 1.0

// Flat outlined chip for the menu-bar corner (project and role selectors).
Rectangle {
    id: root
    property string icon: "folder"
    property string text: "Project"
    property bool dirty: false
    property bool hasMenu: true
    signal clicked()

    implicitHeight: 24
    implicitWidth: 150
    radius: Theme.radiusPanel
    color: mouse.containsMouse ? Theme.chromeHover : "transparent"
    border.width: 1
    border.color: mouse.containsMouse ? "#4e565e" : Theme.chromeOutline

    Row {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: Theme.spBase
        spacing: Theme.spSnug
        Icon { name: root.icon; tone: "dark"; size: 16; anchors.verticalCenter: parent.verticalCenter }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: (root.dirty ? "● " : "") + root.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            font.weight: Font.DemiBold
            color: Theme.textPrimary
            elide: Text.ElideMiddle
            width: Math.max(10, root.width - 64)
        }
    }
    Icon {
        visible: root.hasMenu
        name: "chevron"; tone: "dark"; size: 12
        anchors.right: parent.right
        anchors.rightMargin: Theme.spBase
        anchors.verticalCenter: parent.verticalCenter
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
