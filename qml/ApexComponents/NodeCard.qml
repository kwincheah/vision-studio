import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

// A flow module card: numbered title, input ports on the left, output ports on the right,
// verdict + timing footer.  Port rows are 14 px apart starting 30 px below the card top -
// MainScreen relies on these numbers to draw the wires.
Rectangle {
    id: root
    property string title: "01 ImageAcquisition"
    property string toolName: ""         // the toolbox entry this module is an instance of (shown in the footer)
    property string status: "PASS"       // PASS | FAIL | READY
    property real ms: 0.0
    property bool selected: false
    property var inputs: []              // [{name, type}]
    property var outputs: []             // [{name, type}]
    property var inputState: []          // per input while a wire is dragged: "" | "ok" (can take it) | "dim" | "hot" (snapped target)
    property var outputState: []         // same for outputs (when a wire is dragged backwards from an input)
    property var inputLinked: []         // per input: is a wire attached (changes the tooltip)
    readonly property bool dragging: handle.dragging
    readonly property int headerHeight: 26
    readonly property int rowHeight: 14
    readonly property int rowCount: Math.max(inputs.length, outputs.length, 1)
    signal clicked()
    signal doubleClicked()
    signal moved()
    signal dragStarted()                  // the card began to move (one undo step per drag)
    signal wireStarted(int index)          // drag from output port #index began
    signal inputWireStarted(int index)     // drag from input port #index began (moves its wire, or starts one backwards)
    signal inputWireMoved(point p)
    signal inputWireDropped(point p)
    signal wireMoved(point p)              // pointer, in the parent's coordinates
    signal wireDropped(point p)
    signal inputCleared(int index)         // right-click on a connected input port
    signal contextRequested(point p)       // right-click on the card

    width: 180
    readonly property int toolLine: toolName !== "" ? 14 : 0      // extra footer line naming the toolbox module
    height: headerHeight + rowCount * rowHeight + 22 + toolLine
    radius: 6
    color: Theme.card
    border.width: selected ? 2 : 2
    // Status border from the palette.  It was the literal "#2fa56a"/"#e0585c", a third and
    // fourth shade of "success" and "failure" alongside Theme.okBorder/Theme.errorBorder
    // and the StatusBadge's own fills, so the same PASS verdict drew in two greens on the
    // same screen.  The tokens are the compliant pair (white text clears 4.5:1 on both).
    border.color: selected ? Theme.accent
                          : status === "FAIL" ? Theme.errorBorder : Theme.okBorder

    Text {
        x: 10; y: 5
        text: root.title
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        font.weight: Font.DemiBold
        color: Theme.textPrimary
        elide: Text.ElideRight
        width: root.width - 20
    }
    Rectangle { x: 6; y: 25; width: parent.width - 12; height: 1; color: "#e2e6e9" }

    Repeater {
        model: root.inputs
        delegate: Item {
            x: -5; z: 5; y: root.headerHeight + 4 + index * root.rowHeight
            PortDot { id: dotIn; dataType: modelData.type; dtype: modelData.dtype || ""
                hot: inArea.containsMouse || root.inputState[index] === "hot"; dim: root.inputState[index] === "dim" }
            MouseArea {
                id: inArea
                x: -10; y: -8; width: 28; height: 25; z: 3
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                hoverEnabled: true
                preventStealing: true
                cursorShape: Qt.CrossCursor
                onPressed: function (m) { if (m.button === Qt.LeftButton) root.inputWireStarted(index) }
                onPositionChanged: function (m) { if (pressed) root.inputWireMoved(mapToItem(root.parent, m.x, m.y)) }
                onReleased: function (m) { if (m.button === Qt.LeftButton) root.inputWireDropped(mapToItem(root.parent, m.x, m.y)) }
                onClicked: function (m) { if (m.button === Qt.RightButton) root.inputCleared(index) }
                ToolTip.visible: containsMouse && !pressed
                ToolTip.delay: 400
                ToolTip.text: modelData.name + "  \u00b7  " + (modelData.dtype || modelData.type).toLowerCase()
                              + (root.inputLinked[index] ? "\nDrag to move the wire, right-click to disconnect" : "\nDrag out to link backwards from here")
            }
            Text {
                x: 14; y: -3
                text: modelData.name
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textSecondary
            }
        }
    }
    Repeater {
        model: root.outputs
        delegate: Item {
            x: root.width - 4; z: 5; y: root.headerHeight + 4 + index * root.rowHeight
            PortDot { dataType: modelData.type; dtype: modelData.dtype || ""
                hot: outArea.containsMouse || root.outputState[index] === "hot"; dim: root.outputState[index] === "dim" }
            MouseArea {
                id: outArea
                x: -10; y: -8; width: 28; height: 25; z: 3
                hoverEnabled: true
                cursorShape: Qt.CrossCursor
                preventStealing: true
                ToolTip.visible: containsMouse && !pressed
                ToolTip.delay: 400
                ToolTip.text: modelData.name + "  \u00b7  " + (modelData.dtype || modelData.type).toLowerCase() + "\nDrag to an input to link"
                onPressed: root.wireStarted(index)
                onPositionChanged: function (m) { if (pressed) root.wireMoved(mapToItem(root.parent, m.x, m.y)) }
                onReleased: function (m) { root.wireDropped(mapToItem(root.parent, m.x, m.y)) }
            }
            Text {
                x: -9 - implicitWidth - 6; y: -3
                text: modelData.name
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textSecondary
            }
        }
    }

    Text {
        x: 10
        y: root.height - 18 - root.toolLine
        text: root.status
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        font.weight: Font.Bold
        color: root.status === "FAIL" ? Theme.errorText : Theme.okText
    }
    Text {                                  // which toolbox module this is (the title is the user's own name for it)
        objectName: "cardToolName"
        visible: root.toolName !== ""
        x: 10
        y: root.height - 17
        width: root.width - 20
        text: root.toolName
        elide: Text.ElideRight
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        color: Theme.textMuted
    }
    Text {
        anchors.right: parent.right
        anchors.rightMargin: 10
        y: root.height - 18 - root.toolLine
        text: root.ms.toFixed(1) + " ms"
        font.family: Theme.monoFamily
        font.pixelSize: Theme.fontCaption
        color: Theme.textMuted
    }

    // Moving the card by hand. Qt's own `drag.target` waits for a threshold measured on the zoomed canvas and then
    // moves the card only by the distance PAST it, so the card trailed the pointer (twice as far at 200% zoom).
    // This follows the pointer one-to-one from the first pixel after a small, zoom-independent dead zone.
    MouseArea {
        id: handle
        objectName: "cardHandle"
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: dragging ? Qt.ClosedHandCursor : Qt.OpenHandCursor
        hoverEnabled: true
        property bool dragging: false
        property bool wasDragged: false           // suppresses the click that ends a drag
        property real pressX: 0                    // pointer at the press, in the canvas's coordinates
        property real pressY: 0
        property real startX: 0                    // card position at the press
        property real startY: 0
        readonly property real canvasScale: root.parent && root.parent.scale > 0 ? root.parent.scale : 1.0
        readonly property real deadZone: 4.0       // screen pixels the pointer must travel before the card moves
        onPressed: function (m) {
            if (m.button !== Qt.LeftButton) return
            var p = mapToItem(root.parent, m.x, m.y)
            pressX = p.x; pressY = p.y; startX = root.x; startY = root.y
            dragging = false; wasDragged = false
        }
        onPositionChanged: function (m) {
            if (!pressed || !(pressedButtons & Qt.LeftButton)) return
            var p = mapToItem(root.parent, m.x, m.y)
            var dx = p.x - pressX, dy = p.y - pressY
            if (!dragging) {
                if (Math.sqrt(dx * dx + dy * dy) * canvasScale < deadZone) return
                dragging = true; wasDragged = true
                root.dragStarted()
            }
            root.x = Math.max(0, startX + dx)
            root.y = Math.max(0, startY + dy)
            root.moved()
        }
        onReleased: dragging = false
        onClicked: function (m) {
            if (m.button === Qt.RightButton) root.contextRequested(mapToItem(root.parent, m.x, m.y))
            else if (!wasDragged) root.clicked()
        }
        onDoubleClicked: root.doubleClicked()
        ToolTip.visible: containsMouse && !dragging && root.toolName !== ""
        ToolTip.delay: 700
        ToolTip.text: "Toolbox module: " + root.toolName
    }
}
