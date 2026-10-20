import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// "Create New Solution Project": name, location, template.
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    signal created(string name, string folder, int template)
    title: "Create New Solution Project"
    dialogWidth: 540
    dialogHeight: 400

    Column {
        anchors.fill: parent
        spacing: 12
        Text { text: "Configure solution name, destination directory, and starting template."; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted }
        FormRow { label: "Project Name:"; width: parent.width
            TextBox { id: nameField; width: parent.width; text: "VisionProject_4" } }
        FormRow { label: "Save Location:"; width: parent.width
            Row { spacing: 8; width: parent.width
                TextBox { id: dirField; width: parent.width - 96; text: "C:/Users/you/Documents/ApexVision/Projects" }
                AppButton { text: "Browse..."; width: 88 } } }
        FormRow { label: "Solution Template:"; width: parent.width
            SelectBox { id: tpl; width: parent.width
                model: ["Blank Solution (Standard Acquisition)", "PCB Inspection", "Precision Measurement", "YOLOv11 Object Detection", "Robot Calibration"] } }
    }
    buttons: [
        AppButton { text: "Cancel"; width: 90; onClicked: root.closed() },
        AppButton { text: "Create Project"; kind: "primary"; width: 130
            onClicked: { if (root.backend) root.backend.createProject(nameField.text, dirField.text, tpl.currentIndex)
                         root.created(nameField.text, dirField.text, tpl.currentIndex) } }
    ]
}
