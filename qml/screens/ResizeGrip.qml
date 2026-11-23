import QtQuick 2.15
import ApexTheme 1.0

MouseArea {
    id: grip
    width: 24
    height: 24
    cursorShape: Qt.SizeBDiagCursor

    property Item targetItem: parent
    property real minWidth: 340
    property real maxWidth: 760
    property real minHeight: 380

    property real startX: 0
    property real startY: 0
    property real startW: 0
    property real startH: 0

    onPressed: function(m) {
        if (!targetItem || !targetItem.parent) return;
        var p = mapToItem(targetItem.parent, m.x, m.y);
        startX = p.x;
        startY = p.y;
        startW = targetItem.width;
        startH = targetItem.height;
    }

    onPositionChanged: function(m) {
        if (!pressed || !targetItem || !targetItem.parent) return;
        var p = mapToItem(targetItem.parent, m.x, m.y);

        // Calculate new width & preserve right edge
        var nw = Math.max(minWidth, Math.min(maxWidth, startW - (p.x - startX)));
        targetItem.x += targetItem.width - nw;
        targetItem.width = nw;

        // Calculate new height
        var maxH = targetItem.parent.height - targetItem.y - 8;
        targetItem.height = Math.max(minHeight, Math.min(maxH, startH + (p.y - startY)));
    }

    // Declarative grip lines (matches bottom-left corner diagonal '\')
    Item {
        anchors.fill: parent
        opacity: 0.5

        Rectangle {
            x: 6; y: 8; width: 14; height: 1
            rotation: 45; transformOrigin: Item.TopLeft
            color: Theme.textMuted
        }
        Rectangle {
            x: 6; y: 14; width: 6; height: 1
            rotation: 45; transformOrigin: Item.TopLeft
            color: Theme.textMuted
        }
    }
}
