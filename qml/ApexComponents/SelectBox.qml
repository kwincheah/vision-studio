import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

// Drop-down selector with the shared field look.
Rectangle {
    id: root
    property var model: ["Option A", "Option B"]
    property int currentIndex: 0
    readonly property string currentText: model.length > currentIndex ? model[currentIndex] : ""
    signal activated(int index)

    activeFocusOnTab: true
    Keys.onPressed: function (e) {
        var used = true
        if (e.key === Qt.Key_Space || e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { popup.visible ? popup.close() : popup.open() }
        else if (e.key === Qt.Key_Down && currentIndex < model.length - 1) { currentIndex++; activated(currentIndex) }
        else if (e.key === Qt.Key_Up && currentIndex > 0) { currentIndex--; activated(currentIndex) }
        else used = false
        e.accepted = used
    }

    implicitHeight: Theme.heightButton
    implicitWidth: 120
    radius: Theme.radiusPanel
    color: Theme.fieldBg
    border.width: activeFocus ? 2 : 1
    border.color: activeFocus ? Theme.primary : mouse.containsMouse || popup.visible ? Theme.fieldBorderHover : Theme.fieldBorder

    Text {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.leftMargin: Theme.spBase
        anchors.right: parent.right
        anchors.rightMargin: 26
        text: root.currentText
        elide: Text.ElideRight
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        color: Theme.textPrimary
    }
    Icon {
        name: "chevron"; tone: "dark"; size: 12
        anchors.right: parent.right
        anchors.rightMargin: Theme.spBase
        anchors.verticalCenter: parent.verticalCenter
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: popup.visible ? popup.close() : popup.open()
    }

    Popup {
        id: popup
        y: root.height + 2
        width: root.width
        padding: 2
        background: Rectangle { color: Theme.fieldBg; border.color: Theme.fieldBorder; radius: Theme.radiusPanel }
        contentItem: Column {
            Repeater {
                model: root.model
                delegate: Rectangle {
                    width: popup.width - 4
                    height: 24
                    radius: 2
                    color: hover.containsMouse ? Theme.primary : "transparent"
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.spBase
                        text: modelData
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontBody
                        color: hover.containsMouse ? "#ffffff" : Theme.textPrimary
                    }
                    MouseArea {
                        id: hover
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: { root.currentIndex = index; root.activated(index); popup.close() }
                    }
                }
            }
        }
    }
}
