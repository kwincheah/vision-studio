import QtQuick 2.15
import ApexTheme 1.0

// Single-line text field with the shared field look and a blue focus ring.
Rectangle {
    id: root
    property alias text: input.text
    property string placeholder: ""
    property bool readOnly: false
    property int echoMode: TextInput.Normal     // TextInput.Password for secrets
    signal accepted()
    signal edited()                             // the user typed (not a programmatic change)
    signal editingFinished()                    // Enter pressed or focus left the field

    implicitHeight: Theme.heightButton
    implicitWidth: 200
    radius: Theme.radiusPanel
    color: readOnly ? "#f3f5f6" : Theme.fieldBg
    border.width: 1
    border.color: input.activeFocus ? Theme.primary : hover.containsMouse ? Theme.fieldBorderHover : Theme.fieldBorder

    MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }

    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: Theme.spBase
        anchors.rightMargin: Theme.spBase
        verticalAlignment: TextInput.AlignVCenter
        clip: true
        readOnly: root.readOnly
        echoMode: root.echoMode
        onAccepted: root.accepted()
        onEditingFinished: root.editingFinished()
        onTextEdited: root.edited()
        selectByMouse: true
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: Theme.textPrimary
        selectionColor: Theme.primary
    }
    Text {
        visible: input.text.length === 0 && !input.activeFocus
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: Theme.spBase
        text: root.placeholder
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: Theme.textMuted
    }
}
