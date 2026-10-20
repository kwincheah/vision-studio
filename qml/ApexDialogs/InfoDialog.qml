import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// Generic message dialog (About, Version, Shortcuts, Manual, Communication, ...).
DialogFrame {
    id: root
    property string heading: "Information"
    property string message: ""
    title: heading
    dialogWidth: 520
    dialogHeight: 300

    Text {
        anchors.fill: parent
        text: root.message
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontLabel
        color: Theme.textPrimary
        lineHeight: 1.15
    }
    buttons: [ AppButton { text: "OK"; kind: "primary"; width: 90; onClicked: root.closed() } ]
}
