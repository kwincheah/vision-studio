import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

/*
 * Drop-down menu panel.  items: [ {text, key, shortcut, checked, sub: [..]}, {sep: true} ].
 * A group with `sub` expands in place; choosing an entry emits triggered(key) and closes.
 */
Popup {
    id: root
    property var items: []
    property var expanded: ({})
    signal triggered(string key)

    padding: 4
    width: 300
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function flat() {
        var out = []
        for (var i = 0; i < items.length; i++) {
            var it = items[i]
            out.push({ text: it.text, key: it.key, shortcut: it.shortcut, sep: it.sep === true, group: it.sub !== undefined,
                       open: expanded[it.text] === true, indent: 0, checked: it.checked === true })
            if (it.sub !== undefined && expanded[it.text] === true)
                for (var j = 0; j < it.sub.length; j++)
                    out.push({ text: it.sub[j].text, key: it.sub[j].key, shortcut: "", sep: false, group: false, open: false, indent: 1 })
        }
        return out
    }
    property var rows: flat()
    onItemsChanged: rows = flat()
    onAboutToShow: { expanded = ({}); rows = flat() }
    onExpandedChanged: rows = flat()

    background: Rectangle {
        color: Theme.panelAlt
        border.width: 1
        border.color: Theme.fieldBorder
        radius: Theme.radiusPanel
    }
    contentItem: Column {
        spacing: 0
        Repeater {
            model: root.rows
            delegate: Item {
                width: root.width - 8
                height: modelData.sep ? 9 : 26
                Rectangle { visible: modelData.sep; anchors.centerIn: parent; width: parent.width - 12; height: 1; color: "#d0d4d8" }
                Rectangle {
                    visible: !modelData.sep
                    anchors.fill: parent
                    radius: 3
                    color: itemMouse.containsMouse ? Theme.primary : "transparent"
                    Text {
                        x: 10 + modelData.indent * 18
                        anchors.verticalCenter: parent.verticalCenter
                        text: (modelData.checked ? "✓  " : "") + modelData.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontBody
                        color: itemMouse.containsMouse ? "#ffffff" : Theme.textPrimary
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.group ? (modelData.open ? "▾" : "▸") : (modelData.shortcut ? modelData.shortcut : "")
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontCaption
                        color: itemMouse.containsMouse ? "#e8f2f8" : Theme.textMuted
                    }
                    MouseArea {
                        id: itemMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            if (modelData.group) {
                                var e = root.expanded
                                e[modelData.text] = !(e[modelData.text] === true)
                                root.expanded = e
                                root.rows = root.flat()
                            } else {
                                root.close()
                                root.triggered(modelData.key)
                            }
                        }
                    }
                }
            }
        }
    }
}
