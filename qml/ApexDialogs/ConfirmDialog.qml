import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// "Unsaved changes" question: Save / Discard / Cancel.
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    property string message: "The solution has unsaved changes. Save them before continuing?"
    title: "Unsaved Changes"
    dialogWidth: 460
    dialogHeight: 220
    showClose: false
    escapeCloses: false
    onEscaped: { if (backend) backend.confirmCancel(); closed() }

    Text {
        anchors.fill: parent
        text: root.message
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontLabel
        color: Theme.textPrimary
    }
    buttons: [
        AppButton { text: "Cancel"; width: 90; onClicked: { if (root.backend) root.backend.confirmCancel(); root.closed() } },
        AppButton { text: "Discard"; kind: "danger"; width: 90; onClicked: { root.closed(); if (root.backend) root.backend.confirmDiscard() } },
        AppButton { text: "Save"; kind: "primary"; width: 90; onClicked: { root.closed(); if (root.backend) root.backend.confirmSave() } }
    ]
}
