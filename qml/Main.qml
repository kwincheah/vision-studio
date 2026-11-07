import QtQuick 2.15
import QtQuick.Window 2.15
import ApexTheme 1.0
import "screens"

/*
 * Application window.  Shows the start page first, then the main workspace - the same
 * startup flow as the widget UI.  Switch `startPageVisible` in the Design Studio
 * properties panel to preview either screen.
 */
Window {
    id: window
    width: 1600
    height: 950
    minimumWidth: 1024
    minimumHeight: 640
    visible: true
    title: "Apex Industrial Vision Studio " + (backend ? backend.version : "")
    color: Theme.appBg

    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    property bool startPageVisible: false
    property bool closeApproved: false

    // closing with unsaved edits asks first (Save / Discard / Cancel)
    onClosing: function (close) {
        if (backend && !closeApproved) {
            close.accepted = false
            backend.requestClose()
        }
    }

    MainScreen {
        anchors.fill: parent
    }

    StartScreen {
        id: start
        visible: window.startPageVisible
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        onEnterWorkspace: window.startPageVisible = false
    }

    Connections {
        target: window.backend
        ignoreUnknownSignals: true
        function onStartPageRequested() { window.startPageVisible = true }
        function onWorkspaceRequested() { window.startPageVisible = false }
        function onCloseApproved() { window.closeApproved = true; window.close() }
    }
}
