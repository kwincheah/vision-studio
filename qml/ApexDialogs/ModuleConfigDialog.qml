import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// Module configuration: Input / Output / Run parameters and display setup.
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    property string nodeId: ""
    property string moduleName: "02 IC Alignment"
    property int tab: 0
    property var inputs: SampleData.moduleInputs
    property var params: SampleData.moduleParams
    property string toolType: ""
    title: "Module Configuration - " + moduleName + (toolType !== "" ? "  (" + toolType + ")" : "")
    dialogWidth: 680
    dialogHeight: 520

    onVisibleChanged: if (visible && backend && nodeId !== "") {
        toolType = backend.toolOf(nodeId)
        inputs = backend.moduleInputs(nodeId)
        params = backend.moduleParams(nodeId)
    }

    Column {
        anchors.fill: parent
        spacing: 0
        Row {
            Repeater {
                model: ["Input Params", "Output Params", "Run Params", "Display Setup"]
                delegate: TabButton2 { text: modelData; selected: root.tab === index; onClicked: root.tab = index }
            }
        }
        Rectangle {
            width: parent.width
            height: parent.height - 26
            color: Theme.panelAlt
            border.width: 1; border.color: "#c0c4c8"

            // ---- input params
            Column {
                anchors.fill: parent; anchors.margins: 12; spacing: 10
                visible: root.tab === 0
                Text { width: parent.width; wrapMode: Text.WordWrap; text: "Subscribe the module's input parameters to upstream connection lines. The input follows the connection line it is related to."
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                DataTable { width: parent.width; height: parent.height - 50
                    columns: [ { title: "Param", key: "name", width: 140 }, { title: "Type", key: "type", width: 110 }, { title: "Source", key: "source", width: 0 } ]
                    rows: root.inputs }
            }
            // ---- output params
            Column {
                anchors.fill: parent; anchors.margins: 12; spacing: 10
                visible: root.tab === 1
                Text { width: parent.width; wrapMode: Text.WordWrap; text: "Output parameters produced by this module. Link them to global variables from the Result panel."
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                DataTable { width: parent.width; height: parent.height - 50
                    columns: [ { title: "Param", key: "name", width: 160 }, { title: "Type", key: "type", width: 120 }, { title: "Value", key: "value", width: 0 } ]
                    rows: root.params }
            }
            // ---- run params (editable): each parameter gets the editor that fits it
            Flickable {
                anchors.fill: parent; anchors.margins: 12
                visible: root.tab === 2
                contentHeight: runCol.height + 8
                clip: true
                ScrollBar.vertical: ScrollBar { }
                Column {
                    id: runCol
                    width: parent.width - 14
                    spacing: 12
                    Text { visible: root.params.length === 0; text: "This module has no run parameters."
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted }
                    Repeater {
                        model: root.params
                        delegate: Row {
                            spacing: 14
                            Text { width: 170; height: 26; verticalAlignment: Text.AlignVCenter; text: modelData.label; elide: Text.ElideRight
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary
                                ToolTip.visible: nameMouse.containsMouse; ToolTip.text: modelData.name
                                MouseArea { id: nameMouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton } }
                            ParamEditor { width: runCol.width - 184; spec: modelData
                                onEdited: function (v) { if (root.backend && root.nodeId !== "") root.backend.setParamValue(root.nodeId, modelData.name, v) } }
                        }
                    }
                }
            }
            // ---- display setup
            Column {
                anchors.fill: parent; anchors.margins: 14; spacing: 12
                visible: root.tab === 3
                SectionLabel { width: parent.width; text: "Overlays drawn for this module" }
                CheckLabel { text: "Show module ROI"; checked: true }
                CheckLabel { text: "Show result labels"; checked: true }
                CheckLabel { text: "Show defect boxes"; checked: true }
                SectionLabel { width: parent.width; text: "Colour" }
                Row { spacing: 8
                    Repeater { model: ["#e4b030", "#2fa56a", "#e0585c", "#2b7bb9", "#8a5bd0"]
                        delegate: Rectangle { width: 26; height: 26; radius: 4; color: modelData; border.width: index === 0 ? 2 : 1; border.color: index === 0 ? Theme.textPrimary : "#8b959c" } } }
            }
        }
    }
    buttons: [
        AppButton { text: "Continuous"; width: 110; onClicked: if (root.backend) root.backend.run() },
        AppButton { text: "Execute"; width: 90; onClicked: if (root.backend) root.backend.run() },
        AppButton { text: "OK"; kind: "primary"; width: 90; onClicked: root.closed() }
    ]
}
