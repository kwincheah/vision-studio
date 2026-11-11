import QtQuick 2.15
import ApexTheme 1.0

// Flat tab used by the workspace tabs (Flow Diagram | Operation Interface | Multi-Flow) and the
// right-column tabs.  "light" tabs sit on a panel, "dark" tabs on the chrome strip.
Rectangle {
    id: root
    property string text: "Tab"
    property bool selected: false
    signal clicked()

    // Tabs are controls: a keyboard operator must be able to reach them (Enter/Space
    // activates), and the ring must show which one has focus.
    activeFocusOnTab: true
    Keys.onPressed: function (e) {
        var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return
                          || e.key === Qt.Key_Enter
        if (act) root.clicked()
        e.accepted = act
    }

    implicitHeight: 26
    // The label, the horizontal padding, the 1 px border on each side, and 2 px of slack.
    // Without the border term the tab came out exactly as wide as the text plus its
    // padding, so the glyphs sat flush against the border and a bold (selected) label lost
    // its final pixel - that is why "Create & Publish" rendered clipped in the Plugin
    // Manager while shorter tab labels looked fine.
    implicitWidth: label.implicitWidth + 2 * Theme.spLoose + 2 + 4
    color: selected ? Theme.panelAlt : mouse.containsMouse ? Theme.panelHeader : "#dfe3e6"
    border.width: activeFocus ? 2 : 1
    border.color: activeFocus ? Theme.primary : "#c0c4c8"

    Rectangle {          // amber underline on the selected tab
        visible: root.selected
        anchors.top: parent.top
        width: parent.width
        height: 2
        color: Theme.accent
    }
    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        font.weight: root.selected ? Font.DemiBold : Font.Normal
        color: root.selected ? Theme.textPrimary : Theme.textSecondary
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
