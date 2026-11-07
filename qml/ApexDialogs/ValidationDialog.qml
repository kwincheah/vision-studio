import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// Flow validation report: severity, module, message.
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    property var issues: SampleData.validationIssues
    title: "Flow Validation Diagnostics"
    dialogWidth: 760
    dialogHeight: 380

    onVisibleChanged: if (visible && backend) issues = backend.validateFlow()

    Column {
        anchors.fill: parent
        spacing: 10
        Text {
            property int bad: { var n = 0; for (var i = 0; i < root.issues.length; i++) if (root.issues[i].severity !== "info") n++; return n }
            text: bad === 0 ? "No problems found." : bad + " issue(s) need attention."
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontLabel; font.weight: Font.DemiBold
            color: bad === 0 ? Theme.okText : Theme.errorText
        }
        DataTable {
            width: parent.width
            height: parent.height - 34
            columns: [ { title: "Severity", key: "severity", width: 100 }, { title: "Module", key: "node", width: 190 }, { title: "Message", key: "message", width: 0 } ]
            rows: root.issues
            wrapCells: true
            rowHeight: 40
        }
    }
    buttons: [ AppButton { text: "Close"; width: 90; onClicked: root.closed() } ]
}
