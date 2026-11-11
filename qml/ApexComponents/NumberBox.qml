import QtQuick 2.15
import ApexTheme 1.0

// Numeric field with up / down steppers and an optional unit suffix ("50 ms").
Rectangle {
    id: root
    property real value: 0
    property real from: 0
    property real to: 100000
    property real step: 1
    property int decimals: 0
    property string suffix: ""
    signal edited(real value)

    implicitHeight: Theme.heightButton
    implicitWidth: 130
    radius: Theme.radiusPanel
    color: Theme.fieldBg
    border.width: 1
    border.color: input.activeFocus ? Theme.primary : Theme.fieldBorder

    function commit(v) {
        v = Math.max(from, Math.min(to, v))
        value = v
        edited(v)
    }

    TextInput {
        id: input
        // A TextInput is not in the Tab chain unless it opts in, so the field was
        // unreachable by keyboard: in Flow Settings, Tab went CheckLabel -> Cancel -> OK
        // and skipped both numeric fields entirely.
        activeFocusOnTab: true
        anchors.left: parent.left
        anchors.leftMargin: Theme.spBase
        anchors.right: steppers.left
        anchors.verticalCenter: parent.verticalCenter
        text: root.value.toFixed(root.decimals) + (root.suffix !== "" ? " " + root.suffix : "")
        selectByMouse: true
        Keys.onUpPressed: root.commit(root.value + root.step)
        Keys.onDownPressed: root.commit(root.value - root.step)
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: Theme.textPrimary
        onEditingFinished: { var n = parseFloat(text); if (!isNaN(n)) root.commit(n); text = Qt.binding(function () { return root.value.toFixed(root.decimals) + (root.suffix !== "" ? " " + root.suffix : "") }) }
    }
    MouseArea {      // wheel over the field steps the value
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        // only a field being edited steps with the wheel; otherwise the wheel scrolls the dialog / panel the field sits in
        onWheel: function (w) {
            if (input.activeFocus) root.commit(root.value + (w.angleDelta.y > 0 ? root.step : -root.step))
            else w.accepted = false
        }
    }
    Row {                       // [-] [+] : two full-height 24 px buttons (a stacked up/down spinner is too small to hit)
        id: steppers
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 1
        Repeater {
            model: 2
            delegate: Rectangle {
                width: 24; height: steppers.height
                radius: Theme.radiusControl
                color: stepMouse.pressed ? Theme.buttonPressed : (stepMouse.containsMouse ? Theme.buttonHover : "transparent")
                Text { anchors.centerIn: parent; text: index === 0 ? "−" : "+"
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSubtitle; color: Theme.textPrimary }
                MouseArea { id: stepMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: root.commit(root.value + (index === 0 ? -root.step : root.step)) }
            }
        }
    }
}
