import QtQuick 2.15
import ApexTheme 1.0

// Capsule on/off switch (amber when on).
Rectangle {
    id: root
    property bool checked: false
    signal toggled(bool value)
    function flip() { checked = !checked; toggled(checked) }
    activeFocusOnTab: true
    Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) flip(); e.accepted = act }
    border.width: activeFocus ? 2 : 0
    border.color: Theme.primary

    implicitWidth: 34
    implicitHeight: 18
    radius: height / 2
    color: checked ? Theme.accent : Theme.textMuted
    Behavior on color { ColorAnimation { duration: 120 } }

    Rectangle {
        width: root.height - 4
        height: width
        radius: width / 2
        y: 2
        x: root.checked ? root.width - width - 2 : 2
        color: root.checked ? Theme.textPrimary : Theme.panelAlt
        Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
    }
    MouseArea {
        anchors.fill: parent
        anchors.topMargin: -4; anchors.bottomMargin: -4; anchors.leftMargin: -2; anchors.rightMargin: -2   // 24 px tall hit area
        cursorShape: Qt.PointingHandCursor
        onClicked: root.flip()
    }
}
