import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

/*
 * The palette's scrollbar.
 *
 * Used through the attached form the rest of the interface expects:
 *
 *   Flickable { ScrollBar.vertical: ApexScrollBar { } }
 *
 * The application pins the Basic Controls style (apex_vision/qml_app.py) so this
 * customisation is honoured; the platform's native style ignores contentItem and draws a
 * near-black bar against the light panels.
 */
ScrollBar {
    id: root
    // `horizontal` is FINAL on ScrollBar, so the check is spelled out where it is used.
    readonly property bool isHorizontal: orientation === Qt.Horizontal

    padding: 0
    size: 0.6
    minimumSize: 0.08

    contentItem: Rectangle {
        implicitWidth: root.isHorizontal ? 0 : 6
        implicitHeight: root.isHorizontal ? 6 : 0
        radius: 3
        color: Theme.fieldBorderHover
        opacity: root.pressed ? 1.0 : 0.85
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
    background: Rectangle { color: "transparent" }
}
