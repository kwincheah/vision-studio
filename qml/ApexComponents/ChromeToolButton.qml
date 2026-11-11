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
    // The glyph's tone (an asset folder: light / dark / accent / white).  Empty means
    // "follow the checked state", which is what every existing button wants.
    property string iconTone: ""
    // optional filled variants: "run" (green), "stop" (red), "" (plain)
    property string kind: ""
    // Optional accent border for a plain button (e.g. the amber loop control).  This was
    // passed as a `color` in the screen, which this component does not have, so it silently
    // did nothing.
    property color accentColor: Theme.accent
    signal clicked()
    activeFocusOnTab: true
    Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) clicked(); e.accepted = act }

    implicitWidth: 36
    implicitHeight: 32
    radius: Theme.radiusPanel
    color: {
        if (kind === "run") return mouse.containsMouse ? Theme.runFillDarkHover : Theme.runFillDark
        if (kind === "stop") return mouse.containsMouse ? Theme.stopFillDarkHover : Theme.stopFillDark
        if (checked) return Theme.accentDim
        return mouse.containsMouse ? Theme.railHover : "transparent"
    }
    border.width: activeFocus ? 2 : (kind !== "" || checked ? 1 : 0)
    // On the dark chrome the blue `primary` ring is invisible (1.11:1), so focus uses the
    // light ring token.  The filled run/stop variants keep their own hue when unfocused.
    border.color: activeFocus ? Theme.focusOnChrome
                             : kind === "run" ? Theme.runGreenHover
                             : kind === "stop" ? Theme.stopRedHover : root.accentColor

    Icon {
        anchors.centerIn: parent
        name: root.icon
        tone: root.iconTone !== "" ? root.iconTone
                                  : root.checked ? "dark" : root.tone
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
