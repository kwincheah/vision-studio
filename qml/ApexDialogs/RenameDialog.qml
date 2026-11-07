import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// Rename a module.  The toolbox module it is an instance of never changes (shown below the field).
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    property string nodeId: ""
    property string currentName: ""
    property string toolName: ""
    property string error: ""
    title: "Rename Module"
    dialogWidth: 440
    dialogHeight: 250

    onVisibleChanged: if (visible) {
        error = ""
        nameField.text = currentName
        Qt.callLater(function () { nameField.forceActiveFocus() })
    }

    function commit() {
        if (!backend) { root.closed(); return }
        var problem = backend.renameNode(nodeId, nameField.text)
        if (problem === "") root.closed()
        else error = problem
    }

    Column {
        anchors.fill: parent
        spacing: Theme.spBase
        SectionLabel { width: parent.width; text: "Name" }
        TextBox {
            id: nameField
            objectName: "renameField"
            width: parent.width
            placeholder: "Module name"
            onAccepted: root.commit()
            onTextChanged: root.error = ""
        }
        Text {
            visible: root.error !== ""
            width: parent.width
            text: root.error
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.errorText
        }
        Text {
            width: parent.width
            text: "This is a " + root.toolName + " module. Renaming changes only its label in the flow, results and exports; the module keeps doing the same job."
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted
        }
    }
    buttons: [
        AppButton { objectName: "renameCancel"; text: "Cancel"; width: 90; onClicked: root.closed() },
        AppButton { objectName: "renameOk"; text: "Rename"; kind: "primary"; width: 90; onClicked: root.commit() }
    ]
}
