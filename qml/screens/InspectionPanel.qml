import QtQuick 2.15
import QtQuick.Dialogs
import ApexTheme 1.0
import ApexComponents 1.0

/* Inspection & evaluation dock: Evaluate | Results | Failure Analysis | Experiments | Compare.
   Live through `appInspection` (apex_vision/qml_services.py); sample data in Qt Design Studio. */
Rectangle {
    id: root
    readonly property var svc: typeof appInspection !== "undefined" ? appInspection : null
    readonly property bool busy: svc ? svc.busy : false
    readonly property var experiments: svc ? svc.experiments : SampleData.experiments
    readonly property var failures: svc ? svc.failures : SampleData.failures
    readonly property var metrics: svc ? svc.metrics : [ { name: "Precision", value: "0.874" }, { name: "Recall", value: "0.861" }, { name: "F1", value: "0.867" } ]
    readonly property var perClass: svc ? svc.perClass : []
    property int tab: 0
    signal closeRequested()
    color: Theme.panel
    border.width: 1
    border.color: Theme.fieldBorder

    function names() { var out = []; for (var i = 0; i < experiments.length; i++) out.push(experiments[i].name); return out.length ? out : ["-"] }
    function pushFilter() { if (svc) svc.setFilter(kindBox.currentText, classBox.currentText, minScore.value) }

    FileDialog { id: datasetDialog; title: "Open annotations.json"; nameFilters: ["Annotations (*.json)"]
        onAccepted: if (root.svc) root.svc.loadDataset(selectedFile.toString()) }
    FolderDialog { id: generateDialog; title: "Folder for the PCB defect dataset"
        onAccepted: if (root.svc) root.svc.generateDataset(selectedFolder.toString(), boards.value) }
    FolderDialog { id: storeDialog; title: "Experiment store folder"
        onAccepted: if (root.svc) root.svc.setStore(selectedFolder.toString()) }
    TextEdit { id: clip; visible: false }

    Rectangle {      // dock title
        id: dockTitle
        width: parent.width; height: 26
        color: Theme.panelHeader
        Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "Inspection  ·  Evaluation"
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary }
        Rectangle {
            width: 26; height: 24; radius: 3; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
            color: xMouse.containsMouse ? "#c8ccd0" : "transparent"
            Icon { anchors.centerIn: parent; name: "close"; size: 12 }
            MouseArea { id: xMouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.closeRequested() }
        }
    }
    Row {
        id: tabs
        anchors.top: dockTitle.bottom
        Repeater {
            model: ["Evaluate", "Results", "Failure Analysis", "Experiments", "Compare"]
            delegate: TabButton2 { text: modelData; selected: root.tab === index; onClicked: root.tab = index }
        }
    }
    Item {
        anchors.top: tabs.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 12
        clip: true

        // ---------------------------------------------------------- Evaluate
        Column {
            visible: root.tab === 0
            width: parent.width
            spacing: 10
            SectionLabel { width: parent.width; text: "Dataset" }
            Row { spacing: 8; width: parent.width
                TextBox { width: parent.width - 420; readOnly: true; text: root.svc ? root.svc.datasetText : "No dataset loaded." }
                AppButton { text: "Browse..."; width: 90; onClicked: datasetDialog.open() }
                NumberBox { id: boards; width: 90; value: 40; from: 4; to: 2000; step: 4 }
                AppButton { text: "Generate Dataset..."; width: 170; onClicked: generateDialog.open() } }
            Text { visible: root.svc && root.svc.error !== ""; text: root.svc ? root.svc.error : ""; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.errorText }
            SectionLabel { width: parent.width; text: "Evaluation settings" }
            Row { spacing: 10
                Text { text: "Source:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: source; width: 170; model: ["Reference detector", "Active workflow"] }
                Text { text: "Operating point:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: variant; width: 130; model: ["reference", "conservative"] }
                Text { text: "IoU threshold:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                NumberBox { id: iou; width: 100; value: 0.5; from: 0.05; to: 0.95; step: 0.05; decimals: 2 }
                Text { text: "Confidence:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                NumberBox { id: conf; width: 100; value: 0; from: 0; to: 1; step: 0.05; decimals: 2 }
                CheckLabel { id: layout; text: "Supply board design layout"; checked: true; anchors.verticalCenter: parent.verticalCenter }
            }
            Row { spacing: 8
                AppButton { text: "Run evaluation"; kind: "run"; width: 140; enabledState: !root.busy
                    onClicked: if (root.svc) root.svc.run(source.currentText, variant.currentText, iou.value, conf.value, layout.checked) }
                AppButton { text: "Cancel"; width: 90; enabledState: root.busy; onClicked: if (root.svc) root.svc.cancel() }
                TextBox { id: expName; width: 170; placeholder: "experiment name" }
                AppButton { text: "Save experiment"; width: 140; enabledState: !root.busy; onClicked: if (root.svc) root.svc.saveExperiment(expName.text) }
                AppButton { text: "Copy text report"; width: 140
                    onClicked: { clip.text = root.svc ? root.svc.reportText() : ""; clip.selectAll(); clip.copy() } } }
            Rectangle { visible: root.busy; width: parent.width; height: 8; radius: 4; color: "#d0d4d8"
                Rectangle { width: parent.width * (root.svc ? root.svc.progress : 0); height: parent.height; radius: 4; color: Theme.primary } }
            Text { text: root.svc ? root.svc.progressText : ""; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
        }

        // ---------------------------------------------------------- Results
        Column {
            visible: root.tab === 1
            width: parent.width
            spacing: 12
            Flow { width: parent.width; spacing: 10
                Repeater { model: root.metrics
                    delegate: Rectangle { width: 150; height: 52; radius: Theme.radiusPanel; color: Theme.panelAlt; border.width: 1; border.color: Theme.fieldBorder
                        Column { anchors.centerIn: parent; spacing: 3
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.name; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.value; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSubtitle; font.weight: Font.DemiBold; color: Theme.textPrimary } } } } }
            DataTable { width: parent.width; height: 110
                columns: [ { title: "Class", key: "cls", width: 0 }, { title: "GT", key: "gt", width: 60 }, { title: "TP", key: "tp", width: 60 }, { title: "FP", key: "fp", width: 60 }, { title: "FN", key: "fn", width: 60 },
                           { title: "Precision", key: "p", width: 90 }, { title: "Recall", key: "r", width: 90 }, { title: "F1", key: "f1", width: 90 }, { title: "AP", key: "ap", width: 90 } ]
                rows: root.perClass }
        }

        // ---------------------------------------------------------- Failure analysis
        Column {
            visible: root.tab === 2
            width: parent.width
            spacing: 8
            Row { spacing: 10
                Text { text: "Show:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: kindBox; width: 120; model: ["All", "FP", "FN", "DUPLICATE"]; onActivated: root.pushFilter() }
                Text { text: "Class:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: classBox; width: 120; model: root.svc ? root.svc.labels : ["All"]; onActivated: root.pushFilter() }
                Text { text: "Min score:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                NumberBox { id: minScore; width: 100; value: 0; from: 0; to: 1; step: 0.05; decimals: 2; onEdited: root.pushFilter() }
                Text { text: root.svc ? root.svc.failureSummary : "Run an evaluation to list failures."; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary } }
            Row { spacing: 12; width: parent.width
                DataTable { id: failTable; width: parent.width - 260; height: 150
                    columns: [ { title: "Image", key: "image", width: 0 }, { title: "Kind", key: "kind", width: 90 }, { title: "Class", key: "cls", width: 90 }, { title: "Reason", key: "reason", width: 140 }, { title: "Score", key: "score", width: 60 } ]
                    rows: root.failures
                    onRowClicked: function (row) { if (root.svc) root.svc.showCase(row) } }
                Rectangle { width: 248; height: 150; color: Theme.viewport; clip: true
                    Image { anchors.fill: parent; fillMode: Image.PreserveAspectFit; cache: false; source: root.svc ? root.svc.caseImageUrl : "" }
                    Text { visible: failTable.currentRow < 0; anchors.centerIn: parent; text: "Select a failure"; color: Theme.viewportText; font.pixelSize: Theme.fontCaption } } }
            Row { spacing: 8
                AppButton { text: "Previous"; width: 90; onClicked: if (failTable.currentRow > 0) { failTable.currentRow--; if (root.svc) root.svc.showCase(failTable.currentRow) } }
                AppButton { text: "Next"; width: 90; onClicked: if (failTable.currentRow < root.failures.length - 1) { failTable.currentRow++; if (root.svc) root.svc.showCase(failTable.currentRow) } } }
        }

        // ---------------------------------------------------------- Experiments
        Column {
            visible: root.tab === 3
            width: parent.width
            spacing: 10
            Row { spacing: 8; width: parent.width
                Text { text: "Store:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                TextBox { width: parent.width - 260; readOnly: true; text: root.svc ? root.svc.storeDirectory : "projects\\experiments" }
                AppButton { text: "Change..."; width: 90; onClicked: storeDialog.open() }
                AppButton { text: "Refresh"; width: 80; onClicked: if (root.svc) root.svc.refreshExperiments() } }
            DataTable { width: parent.width; height: 130
                columns: [ { title: "Experiment", key: "name", width: 0 }, { title: "When", key: "when", width: 160 }, { title: "mAP@0.5", key: "map", width: 100 }, { title: "F1", key: "f1", width: 100 } ]
                rows: root.experiments }
        }

        // ---------------------------------------------------------- Compare
        Column {
            visible: root.tab === 4
            width: parent.width
            spacing: 10
            Row { spacing: 10
                Text { text: "Baseline:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: baseBox; width: 220; model: root.names() }
                Text { text: "Compare with:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: otherBox; width: 220; currentIndex: 1; model: root.names() }
                AppButton { text: "Compare"; kind: "primary"; width: 110; onClicked: if (root.svc) root.svc.compare(baseBox.currentText, otherBox.currentText) } }
            DataTable { width: parent.width; height: 120
                columns: [ { title: "Metric", key: "metric", width: 0 }, { title: "Baseline", key: "base", width: 110 }, { title: "Candidate", key: "other", width: 110 }, { title: "Delta", key: "delta", width: 110 } ]
                rows: root.svc ? (root.svc.comparison.rows || []) : [] }
            Text { width: parent.width; wrapMode: Text.WordWrap; text: root.svc && root.svc.comparison.warnings ? root.svc.comparison.warnings.join("\n") : ""
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.warnText }
        }
    }
}
