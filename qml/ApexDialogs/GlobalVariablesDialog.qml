import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// Solution global variables: list, add, delete.
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    readonly property var variables: backend ? backend.globalVariables : SampleData.globalVariables
    title: "Global Variables"
    dialogWidth: 640
    dialogHeight: 620

    Column {
        anchors.fill: parent
        spacing: 10
        Text {
            text: "Solution global variables (shared across multi-flows, communication and logic modules):"
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary
        }
        DataTable {
            id: table
            width: parent.width
            height: parent.height - 210
            columns: [ { title: "Variable Name", key: "name", width: 0 },
                        { title: "Type", key: "type", width: 90 },
                        { title: "Current Value", key: "value", width: 0 },
                        // runtime state: written by the flow, saved, but not an edit
                        { title: "Runtime", key: "runtimeLabel", width: 80 } ]
            rows: root.variables.map(function (v) {
                      var c = {}; for (var k in v) c[k] = v[k]
                      c.runtimeLabel = v.runtime === true ? "state" : "setting"
                      return c })
        }
        Row {
            // The four controls were fixed at 190 + 124 + 170 + 120 = 604 px plus 3 x 8
            // spacing = 628 px, inside a 608 px body, so "+ Add Variable" ended 4 px past
            // the dialog's right edge and was clipped.  The button keeps a fixed width and
            // the three fields share whatever is left.
            id: addRow
            width: parent.width
            spacing: 8
            readonly property int buttonW: 120
            TextBox {
                id: nameField
                width: Math.max(96, (addRow.width - addRow.buttonW - 24) * 0.42)
                placeholder: "Variable name (e.g. g_Total)"
            }
            SelectBox {
                id: typeBox
                width: Math.min(124, Math.max(90, addRow.width * 0.2))
                model: ["Integer", "Float", "String", "Boolean"]
            }
            TextBox {
                id: valueField
                width: Math.max(80, addRow.width - addRow.buttonW - 24
                                   - nameField.width - typeBox.width)
                placeholder: "Initial value"
            }
            AppButton {
                text: "+ Add Variable"; kind: "primary"; width: addRow.buttonW
                onClicked: if (root.backend && nameField.text !== "") {
                    root.backend.setGlobal(nameField.text, typeBox.currentText, valueField.text)
                    nameField.text = ""; valueField.text = ""
                }
            }
        }
        Row {
            id: runtimeRow
            width: parent.width
            spacing: 8
            AppButton {
                objectName: "markRuntime"
                text: "Mark as runtime state"; width: 168
                enabled: table.currentRow >= 0
                onClicked: if (root.backend && table.currentRow >= 0)
                               root.backend.setGlobalRuntime(root.variables[table.currentRow].name, true)
            }
            AppButton {
                objectName: "markSetting"
                text: "Mark as saved setting"; width: 168
                enabled: table.currentRow >= 0
                onClicked: if (root.backend && table.currentRow >= 0)
                               root.backend.setGlobalRuntime(root.variables[table.currentRow].name, false)
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(120, runtimeRow.width - 352)
                wrapMode: Text.WordWrap
                text: "A setting is something you tune: editing it asks you to save. "
                      + "A runtime state value is written by the flow as it runs (a lot tally, "
                      + "a running count): it is still saved with the project, but running the "
                      + "flow does not count as an unsaved change."
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
            }
        }
    }
    buttons: [
        AppButton { text: "Delete Selected"; kind: "danger"; width: 120
            onClicked: if (root.backend && table.currentRow >= 0) root.backend.removeGlobal(root.variables[table.currentRow].name) },
        AppButton { text: "Close"; width: 90; onClicked: root.closed() }
    ]
}
