import QtQuick 2.15
import QtQuick.Dialogs
import ApexTheme 1.0
import ApexComponents 1.0

// Camera management: device list, live preview, exposure / gain / trigger, MVS config import.
// Live through `appCamera` (vm_clone/qml_services.py); sample data in Qt Design Studio.
DialogFrame {
    id: root
    readonly property var cam: typeof appCamera !== "undefined" ? appCamera : null
    readonly property var devices: cam ? cam.devices : SampleData.cameras
    readonly property bool previewing: cam ? cam.previewing : false
    signal lensCalibrationRequested()
    title: "Camera Management - Industrial & Hikrobot MVS Cameras"
    dialogWidth: 900
    dialogHeight: 600

    onVisibleChanged: {
        if (!cam) return
        if (visible && devices.length === 0) cam.refresh()
        if (!visible) cam.stopPreview()
    }
    function push() { if (cam) cam.setParams(exposure.value, gain.value, trigger.currentText, pixel.currentText) }

    FileDialog { id: importDialog; title: "Import MVS configuration"; nameFilters: ["MVS config (*.mvs *.xml)"]
        onAccepted: if (root.cam) root.cam.importMvs(selectedFile.toString()) }
    FileDialog { id: exportDialog; title: "Export MVS configuration"; fileMode: FileDialog.SaveFile; nameFilters: ["MVS config (*.mvs)"]
        onAccepted: if (root.cam) root.cam.exportMvs(selectedFile.toString()) }

    Row {
        anchors.fill: parent
        spacing: 14
        Column {
            width: parent.width * 0.58
            height: parent.height
            spacing: 10
            Text { width: parent.width; wrapMode: Text.WordWrap; text: "Configure GigE Vision, USB3 Vision, Hikrobot MVS, webcams and RTSP streams. Select a camera to preview the live feed and adjust exposure / gain."
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
            DataTable {
                id: table
                width: parent.width; height: 190
                columns: [ { title: "Name / Model", key: "name", width: 0 }, { title: "Type", key: "type", width: 130 }, { title: "Serial / ID", key: "serial", width: 100 } ]
                rows: root.devices
                onRowClicked: function (row) { if (root.cam) { root.cam.select(row); root.push() } }
            }
            Row { spacing: 8
                AppButton { text: "Scan / Refresh Devices"; width: 170; onClicked: if (root.cam) root.cam.refresh() }
                AppButton { text: "Add RTSP Stream..."; width: 160; onClicked: rtsp.visible = !rtsp.visible } }
            Row { id: rtsp; visible: false; spacing: 8
                TextBox { id: rtspUrl; width: 300; placeholder: "rtsp://host:554/stream" }
                AppButton { text: "Add"; width: 70; onClicked: { if (root.cam) root.cam.addStream(rtspUrl.text); rtsp.visible = false } } }
            SectionLabel { width: parent.width; text: "Camera Parameters" }
            Grid { columns: 2; columnSpacing: 14; rowSpacing: 8
                Text { text: "Exposure Time:"; width: 110; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                NumberBox { id: exposure; width: 220; value: 20000; from: 10; to: 1000000; step: 100; decimals: 2; suffix: "us"; onEdited: root.push() }
                Text { text: "Analog Gain:"; width: 110; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                NumberBox { id: gain; width: 220; value: 1; from: 0; to: 48; step: 0.1; decimals: 2; suffix: "x"; onEdited: root.push() }
                Text { text: "Trigger Mode:"; width: 110; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: trigger; width: 220; model: ["Continuous", "Software Trigger", "Hardware Line 0"]; onActivated: root.push() }
                Text { text: "Pixel Format:"; width: 110; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                SelectBox { id: pixel; width: 220; model: ["BGR8 (Color)", "Mono8 (Grayscale)", "Bayer RG8"]; onActivated: root.push() }
                Text { text: "MVS Config:"; width: 110; height: 26; verticalAlignment: Text.AlignVCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                Row { spacing: 8
                    AppButton { text: "Import (*.mvs)"; kind: "primary"; width: 126; onClicked: importDialog.open() }
                    AppButton { text: "Export (*.mvs)"; width: 126; onClicked: exportDialog.open() } }
            }
        }
        Column {
            width: parent.width * 0.42 - 14
            height: parent.height
            spacing: 8
            Rectangle {
                width: parent.width; height: 20; color: "#fbeccf"; radius: 3; border.width: 1; border.color: Theme.warnText
                Text { anchors.centerIn: parent; text: root.cam ? root.cam.sdkStatus : "Hikrobot MVS C SDK: Not installed (emulated mode)"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.warnText }
            }
            SectionLabel { width: parent.width; text: "Live Preview" }
            Rectangle {
                width: parent.width; height: 250; color: Theme.viewport; clip: true
                Image { anchors.fill: parent; anchors.margins: 2; fillMode: Image.PreserveAspectFit; cache: false
                    visible: root.previewing; source: root.cam ? root.cam.previewUrl : "" }
                Text { visible: !root.previewing; anchors.centerIn: parent; text: "Select a camera, then Start Preview"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.viewportText }
            }
            Row { spacing: 10; width: parent.width
                Text { text: "Status: " + (root.cam ? root.cam.status : "Standby"); width: parent.width - 130; wrapMode: Text.WordWrap; maximumLineCount: 2; anchors.verticalCenter: parent.verticalCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.primaryText }
                AppButton { text: root.previewing ? "Stop Preview" : "Start Preview"; kind: root.previewing ? "stop" : "secondary"; width: 110
                    onClicked: if (root.cam) { root.previewing ? root.cam.stopPreview() : root.cam.startPreview() } }
            }
        }
    }
    buttons: [
        AppButton { text: "Lens Calibration Wizard..."; width: 190; onClicked: root.lensCalibrationRequested() },
        AppButton { text: "Close"; kind: "primary"; width: 90; onClicked: root.closed() }
    ]
}
