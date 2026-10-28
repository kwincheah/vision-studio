import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0
import ApexDialogs 1.0
import QtQuick.Dialogs

/* Start page: get started actions, sample templates, recent projects. */
Rectangle {
    id: root
    width: 1080
    height: 680
    color: Theme.panel

    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    readonly property var projects: backend ? backend.recentProjects : SampleData.projects
    property string filter: ""
    property bool showNewProject: false
    signal enterWorkspace()

    FileDialog {
        id: openDialog
        title: "Open Project File"
        nameFilters: ["Vision Solution (*.vmp *.sol *.json *.xml)", "All files (*)"]
        onAccepted: if (root.backend) root.backend.openRecent(root.backend.urlToPath(selectedFile.toString()))
    }

    // ---- header --------------------------------------------------------------------
    Rectangle {
        id: header
        width: parent.width
        height: 64
        color: Theme.panelHeader
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 2; color: Theme.primary }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            x: 24
            spacing: 2
            Text { text: "APEX VISION STUDIO"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontTitle; font.weight: Font.Bold; font.letterSpacing: 1.5; color: Theme.textPrimary }
            Text { text: "Modular Industrial Machine Vision Platform & Flow Orchestration " + (backend ? backend.version : ""); font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted }
        }
    }

    // ---- left column ---------------------------------------------------------------
    Column {
        id: leftCol
        anchors.top: header.bottom
        anchors.topMargin: 22
        x: 24
        width: 340
        spacing: 12
        Text { text: "GET STARTED"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.Bold; color: Theme.textSecondary }

        Repeater {
            model: [ { t: "New Project...", i: "plus", c: Theme.primary }, { t: "Open Project File...", i: "folder", c: Theme.accent } ]
            delegate: Rectangle {
                width: leftCol.width; height: 46
                radius: Theme.radiusPanel
                color: mouseA.containsMouse ? "#ffffff" : Theme.panelAlt
                border.width: 1; border.color: Theme.fieldBorder
                Rectangle { width: 4; height: parent.height; color: modelData.c }
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 20; spacing: 12
                    Icon { name: modelData.i; size: 18; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: modelData.t; font.family: Theme.fontFamily; font.pixelSize: Theme.fontLabel; font.weight: Font.DemiBold; color: Theme.textPrimary; anchors.verticalCenter: parent.verticalCenter }
                }
                MouseArea {
                    id: mouseA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: index === 0 ? root.showNewProject = true : openDialog.open()
                }
            }
        }

        Item { width: 1; height: 6 }
        Text { text: "SAMPLE TEMPLATES"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.Bold; color: Theme.textSecondary }
        Repeater {
            model: ["PCB Inspection & Defects", "Precision Measurement", "YOLOv11 Object Detection", "Robot Coordinate Calibration"]
            delegate: Rectangle {
                width: leftCol.width; height: 36
                radius: Theme.radiusPanel
                color: tplMouse.containsMouse ? "#ffffff" : Theme.panelAlt
                border.width: 1; border.color: "#d8dcdf"
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 14; spacing: 10
                    Icon { name: "bolt"; tone: "accent"; size: 16; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: modelData; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary; anchors.verticalCenter: parent.verticalCenter }
                }
                MouseArea { id: tplMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: if (root.backend) root.backend.newFromTemplate(index) }
            }
        }
    }

    // ---- right column: recent projects ---------------------------------------------
    Item {
        id: rightCol
        anchors.top: header.bottom
        anchors.topMargin: 22
        anchors.left: leftCol.right
        anchors.leftMargin: 50
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.bottom: footer.top
        anchors.bottomMargin: 16

        Row {
            id: recentHead
            spacing: 10
            Text { text: "RECENT PROJECTS"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.Bold; color: Theme.textSecondary; anchors.verticalCenter: parent.verticalCenter }
            Rectangle { width: 28; height: 22; radius: 11; color: Theme.panelHeader; anchors.verticalCenter: parent.verticalCenter
                Text { anchors.centerIn: parent; text: root.projects.length; font.pixelSize: Theme.fontBody; font.weight: Font.Bold; color: Theme.textSecondary } }
        }
        TextBox {
            anchors.right: parent.right
            width: 240
            placeholder: "Filter recent projects..."
            onTextChanged: root.filter = text.toLowerCase()
        }

        Rectangle {
            anchors.top: recentHead.bottom
            anchors.topMargin: 12
            anchors.bottom: parent.bottom
            width: parent.width
            radius: Theme.radiusPanel
            color: Theme.panelAlt
            border.width: 1; border.color: Theme.fieldBorder
            clip: true
            ListView {
                anchors.fill: parent
                model: root.projects
                delegate: Item {
                    width: ListView.view.width
                    height: visible ? 68 : 0
                    visible: root.filter === "" || modelData.name.toLowerCase().indexOf(root.filter) >= 0
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#e2e6e9" }
                    Text { x: 14; y: 12; text: modelData.name; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSubtitle; font.weight: Font.DemiBold; color: Theme.textPrimary }
                    Rectangle { x: 14 + 220; y: 12; width: 50; height: 20; radius: 3; color: Theme.okBg; visible: false }
                    Text { x: 14; y: 40; text: modelData.path; font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary; elide: Text.ElideMiddle; width: parent.width - 28 }
                    Text { anchors.right: openBtn.left; anchors.rightMargin: 16; y: 14; text: modelData.when; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
                    AppButton { id: openBtn; anchors.right: delBtn.left; anchors.rightMargin: 8; y: 10; width: 80; height: 24; text: "Open"; kind: "primary"
                        onClicked: if (root.backend) root.backend.openRecent(modelData.path) }
                    AppButton { id: delBtn; anchors.right: parent.right; anchors.rightMargin: 14; y: 10; width: 74; height: 24; color: "#ff080d"; text: "Delete"; border.color: "#ff080d"; kind: "prrimary"
                        onClicked: if (root.backend) root.backend.removeRecent(modelData.path) }
                }
            }
        }
    }

    // ---- footer --------------------------------------------------------------------
    Rectangle {
        id: footer
        anchors.bottom: parent.bottom
        width: parent.width
        height: 48
        color: Theme.appBg
        Rectangle { width: parent.width; height: 1; color: Theme.fieldBorder }
        Row {
            anchors.verticalCenter: parent.verticalCenter
            x: 24; spacing: 8
            ToggleSwitch { checked: root.backend ? root.backend.showStartPageOnStartup : true; anchors.verticalCenter: parent.verticalCenter
                onToggled: function (value) { if (root.backend) root.backend.setShowStartPageOnStartup(value) } }
            Text { text: "Show Start Page on startup"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontLabel; color: Theme.textSecondary; anchors.verticalCenter: parent.verticalCenter }
        }

    }

    // ---- New Project dialog --------------------------------------------------------
    NewProjectDialog {
        anchors.fill: parent
        visible: root.showNewProject
        onClosed: root.showNewProject = false
        onCreated: { root.showNewProject = false; root.enterWorkspace() }
    }
}
