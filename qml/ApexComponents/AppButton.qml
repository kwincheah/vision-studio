import QtQuick 2.15
import ApexTheme 1.0

// Standard push button.  kind: "secondary" (default), "primary" (blue), "run" (green),
// "stop" (red), "danger" (red outline).
Rectangle {
    id: root
    property string text: "Button"
    property string kind: "secondary"
    property string icon: ""
    property bool enabledState: true
    signal clicked()

    activeFocusOnTab: true
    enabled: enabledState                // a disabled button leaves the focus chain (and loses focus cleanly)
    Keys.onPressed: function (e) {
        var act = e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space
        if (enabledState && act) clicked()
        e.accepted = act          // Tab, Esc ... go on to the dialog
    }

    implicitHeight: Theme.heightButton
    implicitWidth: Math.max(72, label.implicitWidth + (icon !== "" ? 22 : 0) + 2 * Theme.spLoose + 6)
    radius: Theme.radiusPanel
    opacity: enabledState ? 1 : 0.55
    color: {
        var down = mouse.pressed, hov = mouse.containsMouse
        switch (kind) {
        case "primary": return hov ? Theme.primaryHover : Theme.primary
        case "run": return hov ? Theme.runGreenHover : Theme.runGreen
        case "stop": return hov ? Theme.stopRedHover : Theme.stopRed
        case "danger": return hov ? Theme.errorBg : "#fdecee"
        default: return down ? Theme.buttonPressed : hov ? Theme.buttonHover : Theme.buttonBg
        }
    }
    border.width: activeFocus ? 2 : 1
    border.color: {
        if (activeFocus) return Theme.primary
        switch (kind) {
        case "primary": return "#00638f"
        case "run": return "#16a34a"
        case "stop": return "#dc2626"
        case "danger": return Theme.errorBorder
        default: return mouse.containsMouse ? Theme.fieldBorderHover : Theme.fieldBorder
        }
    }

    Row {
        anchors.centerIn: parent
        spacing: Theme.spSnug
        Icon {
            visible: root.icon !== ""
            name: root.icon
            tone: (root.kind === "secondary" || root.kind === "danger") ? "dark" : "white"
            size: 16
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: label
            text: root.text
            anchors.verticalCenter: parent.verticalCenter
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            font.weight: (root.kind === "secondary" || root.kind === "danger") ? Font.Normal : Font.DemiBold
            color: (root.kind === "secondary") ? Theme.textPrimary
                 : (root.kind === "danger") ? Theme.errorText : "#ffffff"
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabledState
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
