import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// Communication Management: the network devices of the solution (TCP server / client, UDP). Receive Data and Send Data use them by name,
// and a device can run a flow whenever a message arrives.
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    readonly property var devices: backend ? backend.commDevices : []
    property string problem: ""
    title: "Communication Management"
    dialogWidth: 860
    dialogHeight: 560

    Timer { interval: 1000; repeat: true; running: root.visible && root.backend !== null; onTriggered: root.backend.refreshComm() }

    Column {
        anchors.fill: parent
        spacing: 10
        Text {
            text: "Devices shared by every flow. Use Receive Data / Send Data with source or target 'Communication Device' and the device name."
            width: parent.width; wrapMode: Text.WordWrap
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary
        }
        DataTable {
            id: table
            objectName: "commTable"
            width: parent.width
            height: parent.height - 190
            columns: [ { title: "Name", key: "name", width: 120 }, { title: "Type", key: "kind", width: 100 }, { title: "Address", key: "endpoint", width: 150 },
                       { title: "State", key: "state", width: 80 }, { title: "Rx", key: "received", width: 50 }, { title: "Tx", key: "sent", width: 50 },
                       { title: "Runs flow", key: "trigger", width: 90 }, { title: "Last message / problem", key: "last", width: 0 } ]
            rows: root.devices
        }
        Text { text: root.problem; visible: root.problem !== ""; width: parent.width; wrapMode: Text.WordWrap; color: Theme.errorBorder
               font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption }
        Row {
            spacing: 8
            TextBox { id: nameField; objectName: "commName"; width: 120; placeholder: "Name (e.g. plc)" }
            SelectBox { id: kindBox; objectName: "commKind"; width: 110; model: ["TCP Server", "TCP Client", "UDP"] }
            TextBox { id: hostField; objectName: "commHost"; width: 130; placeholder: "Address"; text: "0.0.0.0" }
            TextBox { id: portField; objectName: "commPort"; width: 70; placeholder: "Port"; text: "8000" }
            TextBox { id: termField; objectName: "commTerm"; width: 60; placeholder: "End"; text: "\\n" }
            SelectBox { id: flowBox; objectName: "commFlow"; width: 130; model: ["(no flow)"].concat(root.backend ? root.backend.flowNames : []) }
        }
        Row {
            spacing: 8
            TextBox { id: remoteField; width: 170; placeholder: "UDP send to host:port" }
            AppButton {
                text: "+ Add Device"; kind: "primary"; width: 120; objectName: "commAdd"
                onClicked: if (root.backend) {
                    root.problem = root.backend.addCommDevice(nameField.text, kindBox.currentText, hostField.text, parseInt(portField.text) || 0, termField.text,
                                                              flowBox.currentIndex > 0 ? flowBox.currentText : "", false, remoteField.text)
                    if (root.problem === "") nameField.text = ""
                }
            }
        }
    }
    buttons: [
        AppButton { text: "Start"; width: 80; objectName: "commStart"
            onClicked: if (root.backend && table.currentRow >= 0) root.problem = root.backend.startCommDevice(root.devices[table.currentRow].name) },
        AppButton { text: "Stop"; width: 80; objectName: "commStop"
            onClicked: if (root.backend && table.currentRow >= 0) root.backend.stopCommDevice(root.devices[table.currentRow].name) },
        AppButton { text: "Delete Selected"; kind: "danger"; width: 120; objectName: "commDelete"
            onClicked: if (root.backend && table.currentRow >= 0) root.backend.removeCommDevice(root.devices[table.currentRow].name) },
        AppButton { text: "Close"; width: 90; onClicked: root.closed() }
    ]
}
