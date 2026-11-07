import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

/* Tool-box flyout: search field plus a 2-column grid of the modules in one category. */
Rectangle {
    id: root
    property var category: SampleData.toolCategories[0]
    property string filter: ""
    property var categories: SampleData.toolCategories
    signal toolChosen(string toolName)

    width: 230
    color: Theme.panelAlt
    border.width: 1
    border.color: "#c0c4c8"

    function visibleTools() {
        var out = [], f = filter.toLowerCase()
        var cats = categories
        var src = []
        if (f === "") for (var k = 0; k < category.tools.length; k++) src.push({ name: category.tools[k], icon: category.icon })
        else for (var i = 0; i < cats.length; i++)             // search every category; each result keeps its own icon
            for (var j = 0; j < cats[i].tools.length; j++)
                if (cats[i].tools[j].toLowerCase().indexOf(f) >= 0) src.push({ name: cats[i].tools[j], icon: cats[i].icon })
        return src
    }

    Text {
        id: heading
        x: 12; y: 10
        text: root.filter === "" ? root.category.name : "Search results"
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSubtitle; font.weight: Font.DemiBold; color: Theme.textPrimary
    }
    TextBox {
        id: search
        anchors.top: heading.bottom; anchors.topMargin: 8
        x: 10; width: parent.width - 20
        placeholder: "Search modules..."
        onTextChanged: root.filter = text
    }
    Text {
        id: hint
        anchors.top: search.bottom; anchors.topMargin: 6
        x: 12; width: parent.width - 24
        text: "Double-click a module to add it to the flow."
        wrapMode: Text.WordWrap
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted
    }
    Grid {
        anchors.top: hint.bottom; anchors.topMargin: 10
        x: 10
        columns: 2
        spacing: 6
        Repeater {
            model: root.visibleTools()
            delegate: Rectangle {
                width: 100; height: 76
                radius: Theme.radiusPanel
                color: cellMouse.containsMouse ? Theme.accentDim : "transparent"
                border.width: cellMouse.containsMouse ? 1 : 0
                border.color: Theme.accent
                Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 12; name: modelData.icon; tone: "dark"; size: 28 }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 46; width: parent.width - 8
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                    text: modelData.name
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textPrimary
                }
                MouseArea { id: cellMouse; anchors.fill: parent; hoverEnabled: true; onDoubleClicked: root.toolChosen(modelData.name) }
            }
        }
    }
}
