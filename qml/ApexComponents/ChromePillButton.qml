import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

// Icon + label button for the dark toolbar strips (e.g. "AI Gen").
Rectangle {
    id: root
    property string icon: "sparkle"
    property string text: "Action"
    property string tooltip: ""
    property bool checked: false
    signal clicked()

    implicitHeight: 28
    implicitWidth: row.implicitWidth + 2 * Theme.spLoose
    radius: Theme.radiusPanel
    color: checked ? Theme.accent : (mouse.containsMouse ? Theme.railHover : "transparent")
    border.width: activeFocus ? 2 : 1
    border.color: activeFocus ? Theme.primary : Theme.accent
    activeFocusOnTab: true
    Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) clicked(); e.accepted = act }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: Theme.spSnug
        Icon { name: root.icon; tone: root.checked ? "dark" : "light"; size: 16; anchors.verticalCenter: parent.verticalCenter }
        Text {
            text: root.text
            anchors.verticalCenter: parent.verticalCenter
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold
            color: root.checked ? Theme.textPrimary : Theme.textOnChrome
        }
    }
    MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.clicked() }
    ToolTip.visible: mouse.containsMouse && root.tooltip !== ""
    ToolTip.delay: 500
    ToolTip.text: root.tooltip
}
