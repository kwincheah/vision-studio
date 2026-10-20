import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15

/*
 * Keeps keyboard focus inside `scope` while `active`: Tab past the last control wraps to the first,
 * Shift+Tab before the first wraps to the last.  Used by floating panels (AI Gen); modal dialogs have the
 * same behaviour built into DialogFrame.
 */
Item {
    id: root
    property Item scope: parent
    property bool active: false
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
        // popups and menus opened from the panel live in the window overlay: they belong to the panel too
        for (var p = item; p; p = p.parent) if (p === scope || (Overlay.overlay && p === Overlay.overlay)) return true
        return false
    }
    function focusFirst() {
        var list = focusables(scope, [])
        if (list.length > 0) list[0].forceActiveFocus()
    }
    onActiveChanged: lastIdx = -1

    Connections {
        target: root.Window.window
        enabled: root.active
        function onActiveFocusItemChanged() {
            var cur = root.Window.window ? root.Window.window.activeFocusItem : null
            var list = root.focusables(root.scope, [])
            if (cur === null || list.length === 0) return
            if (root.inside(cur)) {
                for (var i = 0; i < list.length; i++) if (list[i] === cur || list[i].activeFocus) root.lastIdx = i
                return
            }
            var target = (root.lastIdx < 0 || root.lastIdx >= list.length - 1) ? 0 : list.length - 1
            list[target].forceActiveFocus()
        }
    }
}
