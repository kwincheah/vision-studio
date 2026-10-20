import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// Per-flow run interval, timeout, stop-on-NG and the flow switch.
DialogFrame {
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    readonly property var settings: backend ? backend.flowSettings : SampleData.flowSettings
    title: "Flow Settings"
    dialogWidth: 420
    dialogHeight: 300

    Grid {
        columns: 2
        columnSpacing: 16
        rowSpacing: 14
        anchors.top: parent.top
        anchors.topMargin: 6
        Text { text: "Run Interval:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary; height: 26; verticalAlignment: Text.AlignVCenter; width: 110 }
        NumberBox { id: interval; width: 200; value: root.settings.runIntervalMs; from: 10; to: 600000; step: 10; suffix: "ms" }
        Text { text: "Flow Timeout:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary; height: 26; verticalAlignment: Text.AlignVCenter; width: 110 }
        NumberBox { id: timeout; width: 200; value: root.settings.timeoutMs; from: 100; to: 3600000; step: 100; suffix: "ms" }
        Text { text: "Stop on NG:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary; height: 20; verticalAlignment: Text.AlignVCenter; width: 110 }
        CheckLabel { id: stopOnNg; text: "Halt continuous cycle on NG defect"; checked: root.settings.stopOnNg }
        Text { text: "Flow Switch:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary; height: 20; verticalAlignment: Text.AlignVCenter; width: 110 }
        CheckLabel { id: enabledBox; text: "Enable flow execution"; checked: root.settings.enabled }
    }
    buttons: [
        AppButton { text: "Cancel"; width: 90; onClicked: root.closed() },
        AppButton { text: "OK"; kind: "primary"; width: 90
            onClicked: { if (root.backend) root.backend.applyFlowSettings(interval.value, timeout.value, stopOnNg.checked, enabledBox.checked)
                         root.closed() } }
    ]
}
