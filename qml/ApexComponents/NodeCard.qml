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
    border.color: selected ? Theme.accent : status === "FAIL" ? "#e0585c" : "#2fa56a"

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
        font.pixelSize: Theme.fontMicro
        color: Theme.textMuted
    }

    MouseArea {
        anchors.fill: parent
        drag.target: root
        drag.minimumX: 0
        drag.minimumY: 0
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.OpenHandCursor
        onClicked: function (m) {
            if (m.button === Qt.RightButton) root.contextRequested(mapToItem(root.parent, m.x, m.y))
            else root.clicked()
        }
        onDoubleClicked: root.doubleClicked()
        hoverEnabled: true
        ToolTip.visible: containsMouse && !drag.active && root.toolName !== ""
        ToolTip.delay: 700
        ToolTip.text: "Toolbox module: " + root.toolName
        drag.onActiveChanged: if (drag.active) root.dragStarted()
        onPositionChanged: if (drag.active) root.moved()
    }
}
