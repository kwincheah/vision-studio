import QtQuick 2.15
import ApexTheme 1.0

// Small caps-style section heading with a hairline rule.
Item {
    id: root
    property string text: "Section"
    implicitHeight: 22
    implicitWidth: 200

    Text {
        id: label
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        font.weight: Font.DemiBold
        color: Theme.textSecondary
    }
    Rectangle {
        anchors.left: label.right
        anchors.leftMargin: 8
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: 1
        color: "#cfd4d8"
    }
}
