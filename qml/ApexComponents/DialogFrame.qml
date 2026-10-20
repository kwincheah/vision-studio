import QtQuick 2.15
import QtQuick.Window 2.15
import ApexTheme 1.0

/*
 * Modal dialog chrome: dimmed scrim, titled panel with a close button, a content area and a
 * right-aligned button row.  Put the dialog body inside as children; put buttons in `buttons`.
 *
 *   DialogFrame { title: "Settings"; dialogWidth: 520; dialogHeight: 360
 *       onClosed: ...
 *       Text { ... }                       // body
 *       buttons: [ AppButton { text: "OK" } ]
 *   }
 */
Item {
    id: root
    property string title: "Dialog"
    property int dialogWidth: 560
    property int dialogHeight: 400
    property bool showClose: true
    default property alias content: body.data
    property alias buttons: buttonRow.data
    property bool escapeCloses: true      // Esc closes the dialog (a question overrides this)
    signal closed()
    signal escaped()

    focus: visible
    onVisibleChanged: if (visible) { lastIdx = -1; forceActiveFocus() }

    // Esc works wherever the keyboard focus is inside the dialog
    Shortcut {
        sequence: "Escape"
        enabled: root.visible
        onActivated: { if (root.escapeCloses) root.closed(); root.escaped() }
    }

    // Keyboard focus stays inside a modal dialog: if Tab would leave it, wrap to the other end
    property int lastIdx: -1
    function focusables(item, out) {
        var kids = item.children
        for (var i = 0; i < kids.length; i++) {
            var k = kids[i]
            if (!k.visible || !k.enabled) continue
            if (k.activeFocusOnTab) out.push(k)
            focusables(k, out)
        }
        return out
    }
    function inside(item) {
        for (var p = item; p; p = p.parent) if (p === root) return true
        return false
    }
    Connections {
        target: root.Window.window
        enabled: root.visible
        function onActiveFocusItemChanged() {
            var cur = root.Window.window ? root.Window.window.activeFocusItem : null
            var list = root.focusables(panel, [])
            if (cur === null || list.length === 0) return
            if (root.inside(cur)) {
                for (var i = 0; i < list.length; i++) if (list[i] === cur || list[i].activeFocus) root.lastIdx = i
                return
            }
            // focus escaped the modal: Tab past the last control wraps to the first, Shift+Tab to the last
            var target = (root.lastIdx < 0 || root.lastIdx >= list.length - 1) ? 0 : list.length - 1
            list[target].forceActiveFocus()
        }
    }

    // scrim - clicking outside does not dismiss (these dialogs hold edits)
    Rectangle { anchors.fill: parent; color: "#80000000"; MouseArea { anchors.fill: parent } }

    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(root.dialogWidth, root.width - 40)
        height: Math.min(root.dialogHeight, root.height - 40)
        radius: Theme.radiusPanel
        color: Theme.panel
        border.width: 1
        border.color: Theme.fieldBorder

        Rectangle {          // title bar
            id: bar
            width: parent.width
            height: 34
            radius: Theme.radiusPanel
            color: Theme.panelHeader
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: Theme.radiusPanel; color: parent.color }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#c0c4c8" }
            Text {
                x: 14
                anchors.verticalCenter: parent.verticalCenter
                text: root.title
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontLabel
                font.weight: Font.DemiBold
                color: Theme.textPrimary
            }
            Rectangle {
                visible: root.showClose
                width: 24; height: 24; radius: Theme.radiusControl
                anchors.right: parent.right; anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                color: closeMouse.containsMouse ? "#c8ccd0" : "transparent"
                Icon { anchors.centerIn: parent; name: "close"; size: 14 }
                MouseArea { id: closeMouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.closed() }
            }
        }

        Item {
            id: body
            anchors.top: bar.bottom
            anchors.bottom: footer.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: Theme.spSection
        }

        Item {
            id: footer
            anchors.bottom: parent.bottom
            width: parent.width
            height: buttonRow.children.length > 0 ? 52 : 0
            Rectangle { visible: footer.height > 0; width: parent.width; height: 1; color: "#d0d4d8" }
            Row {
                id: buttonRow
                anchors.right: parent.right
                anchors.rightMargin: Theme.spSection
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
            }
        }
    }
}
