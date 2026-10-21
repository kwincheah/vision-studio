import QtQuick 2.15
import QtQuick.Dialogs
import ApexTheme 1.0
import ApexComponents 1.0

// Camera lens distortion calibration wizard: target settings, views pool, preview, solution.
// Live through `appLens` (apex_vision/qml_services.py); sample data in Qt Design Studio.
DialogFrame {
    id: root
    readonly property var lens: typeof appLens !== "undefined" ? appLens : null
    readonly property var views: lens ? lens.views : SampleData.calibrationViews
    readonly property var result: lens ? lens.result : ({ calibrated: false, rms: 0, valid_views: 2, fx: 0, fy: 0, cx: 0, cy: 0, k1: 0, k2: 0, k3: 0, p1: 0, p2: 0 })
    readonly property string status: lens ? lens.status : "Add calibration views, then compute."
    property int viewMode: 0
    readonly property var modes: ["Detected Corners", "Distorted (Raw)", "Undistorted (Rectified)"]
    title: "Camera Lens Distortion Calibration"
    dialogWidth: 1120
    dialogHeight: 700

    function pushPattern() {
        if (lens) lens.setPattern(patternBox.currentText, cols.value, rows.value, square.value)
    }
    function fmt(v, d) { return result.calibrated ? Number(v).toFixed(d) : "--" }

    FileDialog { id: addDialog; title: "Select calibration images"; fileMode: FileDialog.OpenFiles
        nameFilters: ["Images (*.png *.jpg *.jpeg *.bmp *.tif)", "All files (*)"]
        onAccepted: if (root.lens) root.lens.addFiles(selectedFiles.map(function (u) { return u.toString() })) }
    FileDialog { id: saveDialog; title: "Save calibration profile"; fileMode: FileDialog.SaveFile
        nameFilters: ["Calibration profile (*.calib.json)"]
        onAccepted: if (root.lens) root.lens.saveProfile(selectedFile.toString()) }
    FileDialog { id: loadDialog; title: "Load calibration profile"
        nameFilters: ["Calibration profile (*.json)"]
        onAccepted: if (root.lens) root.lens.loadProfile(selectedFile.toString()) }

    Column {
        anchors.fill: parent
        spacing: 12
        Row {
            spacing: 14
            Text { text: "Target Pattern:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary }
            SelectBox { id: patternBox; width: 160; model: ["Chessboard", "Circles Grid", "Asymmetric Circles"]; onActivated: root.pushPattern() }
            Text { text: "Inner Cols:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
            NumberBox { id: cols; width: 90; value: 9; from: 3; to: 40; onEdited: root.pushPattern() }
            Text { text: "Inner Rows:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
            NumberBox { id: rows; width: 90; value: 6; from: 3; to: 40; onEdited: root.pushPattern() }
            Text { text: "Square Size:"; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
            NumberBox { id: square; width: 130; value: 25; from: 0.1; to: 500; step: 0.5; decimals: 2; suffix: "mm"; onEdited: root.pushPattern() }
        }
        Row {
            width: parent.width
            height: parent.height - 44
            spacing: 12
            // views pool
            Column {
                width: 250; height: parent.height; spacing: 8
                SectionLabel { width: parent.width; text: "Calibration Views Pool" }
                DataTable { id: viewTable; width: parent.width; height: parent.height - 120
                    currentRow: root.lens ? root.lens.currentView : 0
                    columns: [ { title: "View", key: "name", width: 0 }, { title: "Corners", key: "corners", width: 64 } ]
                    rows: root.views
                    onRowClicked: function (row) { if (root.lens) root.lens.selectView(row) } }
                Row { spacing: 6
                    AppButton { text: "Add Files..."; width: 114; onClicked: addDialog.open() }
                    AppButton { text: "Capture Live"; width: 114; onClicked: if (root.lens) root.lens.capture() } }
                Row { spacing: 6
                    AppButton { text: "Generate Synthetic"; width: 114; onClicked: if (root.lens) root.lens.addSynthetic() }
                    AppButton { text: "Remove"; width: 55; kind: "danger"; onClicked: if (root.lens && viewTable.currentRow >= 0) root.lens.remove(viewTable.currentRow) }
                    AppButton { text: "Clear"; width: 55; kind: "danger"; onClicked: if (root.lens) root.lens.clear() } }
            }
            // preview
            Column {
                width: parent.width - 250 - 270 - 24; height: parent.height; spacing: 8
                Row { spacing: 18
                    Repeater { model: root.modes
                        delegate: Row { spacing: 6
                            Rectangle { width: 14; height: 14; radius: 7; color: root.viewMode === index ? Theme.primary : Theme.fieldBg; border.width: 1; border.color: Theme.fieldBorderHover
                                Rectangle { visible: root.viewMode === index; anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: "#fff" }
                                MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: { root.viewMode = index; if (root.lens) root.lens.setMode(modelData) } } }
                            Text { text: modelData; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary } } } }
                Rectangle { width: parent.width; height: parent.height - 56; color: "#f4f4f4"; border.width: 1; border.color: Theme.fieldBorder; clip: true
                    Image { anchors.fill: parent; anchors.margins: 4; fillMode: Image.PreserveAspectFit; cache: false
                        visible: root.lens !== null && root.views.length > 0
                        source: root.lens ? root.lens.previewUrl : "" }
                    Grid { visible: root.lens === null; anchors.centerIn: parent; columns: 9; spacing: 0
                        Repeater { model: 54; delegate: Rectangle { width: 36; height: 36; color: ((Math.floor(index / 9) + index % 9) % 2) ? "#f4f4f4" : "#1c1c1c" } } }
                    Text { visible: root.lens !== null && root.views.length === 0; anchors.centerIn: parent; text: "Add calibration views to begin"
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted } }
                Text { width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 2; text: root.status; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
            }
            // solution
            Column {
                width: 270; height: parent.height; spacing: 8
                SectionLabel { width: parent.width; text: "Calibration Solution" }
                Rectangle { width: parent.width; height: 30; radius: 3
                    color: root.result.calibrated ? Theme.okBg : "#fbeccf"
                    Text { anchors.centerIn: parent; text: root.result.calibrated ? "CALIBRATED (RMS " + root.result.rms.toFixed(4) + " px)" : "NOT CALIBRATED"
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.Bold
                        color: root.result.calibrated ? Theme.okText : Theme.warnText } }
                Grid { columns: 2; columnSpacing: 10; rowSpacing: 6
                    Repeater {
                        model: [ "Valid Views:", String(root.result.valid_views),
                                 "Focal Length (fx, fy):", root.fmt(root.result.fx, 1) + ", " + root.fmt(root.result.fy, 1),
                                 "Principal Point (cx, cy):", root.fmt(root.result.cx, 1) + ", " + root.fmt(root.result.cy, 1),
                                 "Radial (k1, k2, k3):", root.fmt(root.result.k1, 4) + ", " + root.fmt(root.result.k2, 4) + ", " + root.fmt(root.result.k3, 4),
                                 "Tangential (p1, p2):", root.fmt(root.result.p1, 4) + ", " + root.fmt(root.result.p2, 4) ]
                        delegate: Text { text: modelData; width: index % 2 ? 110 : 140; wrapMode: Text.WordWrap; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: index % 2 ? Theme.textPrimary : Theme.textSecondary } } }
                Item { width: 1; height: 6 }
                AppButton { width: parent.width; text: "Compute Lens Calibration"; kind: "primary"; onClicked: if (root.lens) root.lens.compute() }
                AppButton { width: parent.width; text: "Save Profile (*.calib.json)..."; onClicked: saveDialog.open() }
                AppButton { width: parent.width; text: "Load Profile..."; onClicked: loadDialog.open() }
                AppButton { width: parent.width; text: "Apply to Active Flow"; kind: "run"; onClicked: if (root.lens) root.lens.apply() }
            }
        }
    }
    buttons: [ AppButton { text: "Close"; width: 90; onClicked: root.closed() } ]
}
