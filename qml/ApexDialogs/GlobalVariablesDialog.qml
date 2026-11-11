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
    dialogHeight: 470

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
            height: parent.height - 120
            columns: [ { title: "Variable Name", key: "name", width: 0 }, { title: "Type", key: "type", width: 110 }, { title: "Current Value", key: "value", width: 0 } ]
            rows: root.variables
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
    }
    buttons: [
        AppButton { text: "Delete Selected"; kind: "danger"; width: 120
            onClicked: if (root.backend && table.currentRow >= 0) root.backend.removeGlobal(root.variables[table.currentRow].name) },
        AppButton { text: "Close"; width: 90; onClicked: root.closed() }
    ]
}
