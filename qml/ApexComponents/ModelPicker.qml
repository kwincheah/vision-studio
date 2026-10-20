import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0

/*
 * One editable model field: type any model id, or pick one from the suggestions below it.
 *   choices: [{id, label}]   value: current model id   alwaysOpen: keep the list expanded (quick picker)
 * Typing filters the list; Enter accepts what is typed; clicking a suggestion accepts it.
 */
Column {
    id: root
    property var choices: []
    property string value: ""
    property bool loading: false
    property bool alwaysOpen: false
    property bool expanded: false
    property int maxRows: 6
    signal accepted(string modelId)          // the user picked or confirmed a model
    signal refreshRequested()

    spacing: 2
    readonly property string typed: field.text.trim()
    readonly property var shown: {
        var t = typed.toLowerCase(), out = []
        for (var i = 0; i < choices.length; i++)
            if (t === "" || t === value.toLowerCase() || choices[i].id.toLowerCase().indexOf(t) >= 0 || (choices[i].label || "").toLowerCase().indexOf(t) >= 0) out.push(choices[i])
        return out
    }
    readonly property bool inList: { for (var i = 0; i < choices.length; i++) if (choices[i].id === typed) return true; return false }
    readonly property bool listOpen: (alwaysOpen || expanded) && shown.length > 0

    function setText(t) { field.text = t }
    onValueChanged: if (field.text !== value) field.text = value
    onVisibleChanged: if (!visible) expanded = false          // reopening starts with the list closed

    Row {
        width: parent.width
        spacing: Theme.spSnug
        TextBox {
            id: field
            objectName: "aiModelField"
            width: parent.width - 28 - 28 - 2 * Theme.spSnug
            text: root.value
            placeholder: "Model id, e.g. gpt-4.1"
            onEdited: root.expanded = true
            onAccepted: { root.expanded = false; if (root.typed !== "") root.accepted(root.typed) }
            onEditingFinished: if (root.typed !== "" && root.typed !== root.value) root.accepted(root.typed)
        }
        Rectangle {                              // show / hide the suggestions
            objectName: "aiModelToggle"
            width: 28; height: field.height; radius: Theme.radiusPanel
            visible: !root.alwaysOpen
            color: tm.containsMouse ? Theme.buttonHover : Theme.buttonBg
            border.width: activeFocus ? 2 : 1; border.color: activeFocus ? Theme.primary : Theme.fieldBorder
            activeFocusOnTab: !root.alwaysOpen
            Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) root.expanded = !root.expanded; e.accepted = act }
            Icon { anchors.centerIn: parent; name: "chevron"; size: 12; rotation: root.listOpen ? 180 : 0 }
            MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.expanded = !root.expanded }
            ToolTip.visible: tm.containsMouse; ToolTip.delay: 500; ToolTip.text: "Show suggestions"
        }
        Rectangle {                              // load the provider's real model list
            objectName: "aiFetchModels"
            width: 28; height: field.height; radius: Theme.radiusPanel
            color: rm.containsMouse ? Theme.buttonHover : Theme.buttonBg
            border.width: activeFocus ? 2 : 1; border.color: activeFocus ? Theme.primary : Theme.fieldBorder
            activeFocusOnTab: true
            Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) root.refreshRequested(); e.accepted = act }
            Icon { anchors.centerIn: parent; name: "loop"; size: 14; opacity: root.loading ? 0.4 : 1 }
            MouseArea { id: rm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; enabled: !root.loading; onClicked: root.refreshRequested() }
            ToolTip.visible: rm.containsMouse; ToolTip.delay: 500; ToolTip.text: root.loading ? "Loading models..." : "Load the models available to this account"
        }
    }

    Rectangle {                                  // suggestions
        id: list
        objectName: "aiModelList"
        visible: root.listOpen
        width: parent.width
        height: Math.min(root.maxRows, root.shown.length) * 30 + 2
        color: Theme.fieldBg
        border.width: 1; border.color: Theme.fieldBorder
        radius: Theme.radiusPanel
        clip: true
        ListView {
            anchors.fill: parent; anchors.margins: 1
            model: root.shown
            interactive: root.shown.length > root.maxRows
            ScrollBar.vertical: ScrollBar { }
            delegate: Rectangle {
                objectName: "aiModelOption"
                width: ListView.view.width; height: 30
                color: om.containsMouse ? Theme.primary : (modelData.id === root.value ? Theme.accentDim : "transparent")
                Row {
                    anchors.verticalCenter: parent.verticalCenter; x: 8; spacing: Theme.spBase
                    Text { text: modelData.id; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody
                        color: om.containsMouse ? "#ffffff" : Theme.textPrimary }
                    Text { visible: (modelData.label || "") !== ""; text: modelData.label; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                        color: om.containsMouse ? "#e8f2f8" : Theme.textMuted }
                }
                MouseArea { id: om; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                    onClicked: { var picked = modelData.id; root.expanded = false; root.accepted(picked); field.text = picked } }   // set the text last: it rebuilds this list
            }
        }
    }
}
