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
    // The selected module's Display Setup; refreshed with the rest of the dialog.
    property var display: ({ roi: true, labels: true, boxes: true, colour: "#e4b030" })
    title: "Module Configuration - " + moduleName + (toolType !== "" ? "  (" + toolType + ")" : "")
    dialogWidth: 680
    dialogHeight: 740

    // After an edit, options may start or stop applying (e.g. the file path once Source Type is Camera): rebuild the list only then.
    function refreshParams() {
        if (!backend || nodeId === "") return
        var fresh = backend.moduleParams(nodeId), changed = fresh.length !== params.length
        for (var i = 0; !changed && i < fresh.length; i++)
            if (fresh[i].active !== params[i].active || fresh[i].name !== params[i].name || (fresh[i].kind === "device" && fresh[i].choices.length !== params[i].choices.length)
                || (fresh[i].active !== false && fresh[i].native !== params[i].native && fresh[i].kind === "device"))
                changed = true
        if (changed) params = fresh
    }

    // One Display Setup field: write it, then re-read so the control shows what was stored
    // (a refused value must not leave the checkbox showing a state the project does not have).
    function setDisplay(key, value) {
        if (!backend || nodeId === "") return
        backend.setModuleDisplay(nodeId, key, value)
        display = backend.selectedDisplay
    }

    onVisibleChanged: if (visible && backend && nodeId !== "") {
        toolType = backend.toolOf(nodeId)
        inputs = backend.moduleInputs(nodeId)
        params = backend.moduleParams(nodeId)
        display = backend.selectedDisplay
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
                id: runFlick
                anchors.fill: parent; anchors.margins: 12
                visible: root.tab === 2
                contentHeight: runCol.height + 8
                clip: true
                ScrollBar.vertical: ApexScrollBar { }
                Column {
                    id: runCol
                    width: parent.width - 14
                    spacing: 12
                    Text { visible: root.params.length === 0; text: "This module has no run parameters."
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted }
                    Repeater {
                        model: root.params
                        // One editor per parameter.  A script gets the whole width and a
                        // real height; a one-line value keeps the compact label|editor row.
                        // (An earlier version put an editor in each branch of a two-branch
                        // delegate, so every parameter was built twice - two ScriptEditors
                        // for one script, both compiling on every keystroke.)
                        delegate: Item {
                            id: paramRow
                            width: runCol.width
                            readonly property bool wide: modelData.kind === "code"
                            readonly property real editorH: editor.implicitHeight > 0
                                                            ? editor.implicitHeight : 26
                            height: wide ? 30 + editorH : Math.max(26, editorH)

                            Text {
                                id: rowLabel
                                x: 0; y: 0
                                width: paramRow.wide ? paramRow.width : 170
                                height: paramRow.wide ? 26 : paramRow.height
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.label
                                elide: Text.ElideRight
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody
                                font.weight: paramRow.wide ? Font.DemiBold : Font.Normal
                                color: Theme.textPrimary
                                ToolTip.visible: nameMouse.containsMouse
                                ToolTip.text: modelData.name
                                MouseArea { id: nameMouse; anchors.fill: parent; hoverEnabled: true
                                            acceptedButtons: Qt.NoButton }
                            }
                            Text {
                                visible: paramRow.wide
                                x: rowLabel.implicitWidth + 10
                                anchors.verticalCenter: rowLabel.verticalCenter
                                text: "Python \u00b7 Ctrl+Enter applies \u00b7 Ctrl+/ comments \u00b7 Tab indents"
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                                color: Theme.textMuted
                            }
                            ParamEditor {
                                id: editor
                                spec: modelData
                                x: paramRow.wide ? 0 : 184
                                y: paramRow.wide ? 30 : 0
                                width: paramRow.wide ? paramRow.width : runCol.width - 184
                                onEdited: function (v) { if (root.backend && root.nodeId !== "") root.backend.setParamValue(root.nodeId, modelData.name, v); root.refreshParams() }
                            }
                        }
                    }
                }
            }
            // ---- display setup
            Column {
                anchors.fill: parent; anchors.margins: 14; spacing: 12
                visible: root.tab === 3
                SectionLabel { width: parent.width; text: "Overlays drawn for this module" }
                // These were hardcoded `checked: true` with no handler, so they looked live
                // and saved nothing.  They now read and write the module's own Display Setup,
                // which is stored with the project.
                CheckLabel {
                    objectName: "displayRoi"
                    text: "Show module ROI"
                    checked: root.display.roi === true
                    onToggled: function (value) { root.setDisplay("roi", value) }
                }
                CheckLabel {
                    objectName: "displayLabels"
                    text: "Show result labels"
                    checked: root.display.labels === true
                    onToggled: function (value) { root.setDisplay("labels", value) }
                }
                CheckLabel {
                    objectName: "displayBoxes"
                    text: "Show defect boxes"
                    checked: root.display.boxes === true
                    onToggled: function (value) { root.setDisplay("boxes", value) }
                }
                SectionLabel { width: parent.width; text: "Colour" }
                Row {
                    spacing: 8
                    Repeater {
                        model: ["#e4b030", "#2fa56a", "#e0585c", "#2b7bb9", "#8a5bd0"]
                        delegate: Rectangle {
                            objectName: "displayColour" + index
                            width: 26; height: 26; radius: 4
                            color: modelData
                            readonly property bool chosen: String(root.display.colour).toLowerCase() === modelData
                            border.width: chosen ? 3 : 1
                            border.color: chosen ? Theme.textPrimary : "#8b959c"
                            ToolTip.visible: swatchMouse.containsMouse
                            ToolTip.text: "Draw this module's overlays in " + modelData
                            ToolTip.delay: 400
                            MouseArea {
                                id: swatchMouse
                                anchors.fill: parent; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.setDisplay("colour", modelData)
                            }
                        }
                    }
                }
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "Applies to the overlays this module draws. Other modules keep their own settings."
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                    color: Theme.textMuted
                }
            }
        }
    }
    buttons: [
        AppButton { text: "Continuous"; width: 110; onClicked: if (root.backend) root.backend.run() },
        AppButton { text: "Execute"; width: 90; onClicked: if (root.backend) root.backend.run() },
        AppButton { text: "OK"; kind: "primary"; width: 90; onClicked: root.closed() }
    ]
}
