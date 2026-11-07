import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

// Square icon button for the dark toolbar strips.
Rectangle {
    id: root
    property string icon: "save"
    property string tone: "light"
    property bool checked: false
    property string tooltip: ""
    // optional filled variants: "run" (green), "stop" (red), "" (plain)
    property string kind: ""
    signal clicked()
    activeFocusOnTab: true
    Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) clicked(); e.accepted = act }

    implicitWidth: 36
    implicitHeight: 32
    radius: Theme.radiusPanel
    color: {
        if (kind === "run") return mouse.containsMouse ? "#1d4d2e" : "#15351f"
        if (kind === "stop") return mouse.containsMouse ? "#5a242a" : "#3b181c"
        if (checked) return Theme.accentDim
        return mouse.containsMouse ? Theme.railHover : "transparent"
    }
    border.width: activeFocus ? 2 : (kind !== "" || checked ? 1 : 0)
    border.color: kind === "run" ? "#22c55e" : kind === "stop" ? "#ef4444" : Theme.accent

    Icon {
        anchors.centerIn: parent
        name: root.icon
        tone: root.checked ? "dark" : root.tone
        size: 18
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
    ToolTip.visible: mouse.containsMouse && root.tooltip !== ""
    ToolTip.delay: 500
    ToolTip.text: root.tooltip
}
