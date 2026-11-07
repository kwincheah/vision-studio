import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

/*
 * Read-only table with a header, striped rows and a selectable row.
 *   DataTable { columns: [ {title: "Name", key: "name", width: 0},       // width 0 = stretch
 *                          {title: "Type", key: "type", width: 120} ]
 *               rows: [ {name: "a", type: "int"} ] }
 */
Rectangle {
    id: root
    property var columns: []
    property var rows: []
    property int currentRow: -1
    property int rowHeight: 28
    property bool mono: false
    property bool wrapCells: false        // long values wrap to two lines instead of being elided
    signal rowClicked(int row)

    color: Theme.fieldBg
    border.width: 1
    border.color: Theme.fieldBorder
    radius: Theme.radiusPanel
    clip: true

    function colWidth(i) {
        var fixed = 0, stretch = 0
        for (var k = 0; k < columns.length; k++) {
            if (columns[k].width > 0) fixed += columns[k].width; else stretch++
        }
        return columns[i].width > 0 ? columns[i].width : Math.max(60, (root.width - 2 - fixed) / Math.max(1, stretch))
    }
    function colX(i) {
        var x = 0
        for (var k = 0; k < i; k++) x += colWidth(k)
        return x
    }

    Rectangle {
        id: head
        width: parent.width - 2
        x: 1; y: 1
        height: 28
        color: Theme.panelHeader
        Repeater {
            model: root.columns
            delegate: Text {
                x: root.colX(index) + 10
                anchors.verticalCenter: parent.verticalCenter
                width: root.colWidth(index) - 14
                text: modelData.title
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                color: Theme.textSecondary
            }
        }
    }

    ListView {
        anchors.top: head.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 1
        model: root.rows
        clip: true
        delegate: Rectangle {
            width: ListView.view.width
            height: root.rowHeight
            color: index === root.currentRow ? Theme.accentDim : (index % 2 ? "#f1f4f5" : Theme.fieldBg)
            property var rowData: modelData
            Repeater {
                model: root.columns
                delegate: Text {
                    x: root.colX(index) + 10
                    anchors.verticalCenter: parent.verticalCenter
                    width: root.colWidth(index) - 14
                    text: rowData[modelData.key] === undefined ? "" : String(rowData[modelData.key])
                    elide: Text.ElideRight
                    wrapMode: root.wrapCells ? Text.WordWrap : Text.NoWrap
                    maximumLineCount: root.wrapCells ? 2 : 1
                    font.family: root.mono ? Theme.monoFamily : Theme.fontFamily
                    font.pixelSize: Theme.fontBody
                    color: Theme.textPrimary
                }
            }
            MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; onClicked: { root.currentRow = index; root.rowClicked(index) } }
            ToolTip.visible: rowMouse.containsMouse && root.wrapCells === false && cellsElided()
            ToolTip.delay: 600
            ToolTip.text: JSON.stringify(rowData).replace(/[{}\"]/g, "").replace(/,/g, "   ")
            function cellsElided() { for (var i = 0; i < root.columns.length; i++) { var v = rowData[root.columns[i].key]; if (v !== undefined && String(v).length * 6.5 > root.colWidth(i) - 14) return true } return false }
        }
    }
}
