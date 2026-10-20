import QtQuick 2.15
import ApexTheme 1.0

// Checkbox with a caption (amber when checked, like the widget UI).
Item {
    id: root
    property bool checked: false
    property string text: "Option"
    signal toggled(bool value)

    implicitWidth: row.implicitWidth
    implicitHeight: 24
    activeFocusOnTab: true
    Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) { checked = !checked; toggled(checked) } e.accepted = act }

    Row {
        id: row
        spacing: 8
        anchors.verticalCenter: parent.verticalCenter
        Rectangle {
            width: 16; height: 16; radius: Theme.radiusPanel
            anchors.verticalCenter: parent.verticalCenter
            color: root.checked ? Theme.accent : Theme.fieldBg
            border.width: root.activeFocus ? 2 : 1
            border.color: root.activeFocus ? Theme.primary : root.checked ? Theme.accentBorder : "#8b959c"
            Icon { visible: root.checked; anchors.centerIn: parent; name: "check"; size: 12 }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.textPrimary
        }
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: { root.checked = !root.checked; root.toggled(root.checked) }
    }
}
