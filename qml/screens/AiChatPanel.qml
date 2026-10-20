import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Dialogs
import ApexTheme 1.0
import ApexComponents 1.0

/*
 * AI Gen: a floating chat that builds flows from a description.
 * Drag the title bar to move it, drag the lower-left corner to resize it.  Without an API key it shows the
 * key setup; with one it is a chat whose answers can include a flow to add to the project.
 */
Rectangle {
    id: root
    readonly property var svc: typeof appAI !== "undefined" ? appAI : null
    readonly property var msgs: svc ? svc.messages : SampleData.aiMessages
    readonly property bool hasKey: svc ? svc.ready : true
    readonly property bool busy: svc ? svc.busy : false
    property bool settingsOpen: false
    signal closeRequested()

    width: 440
    height: 580
    radius: Theme.radiusPanel
    color: Theme.panel
    border.width: 1
    border.color: Theme.fieldBorder
    clip: true
    focus: visible
    Keys.onEscapePressed: root.closeRequested()

    FocusTrap { id: trap; scope: root; active: root.visible }

    // ---- title bar (drag handle): title, provider / model, three-dot menu, close
    Rectangle {
        id: bar
        width: parent.width
        height: 46
        color: Theme.panelHeader
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.fieldBorder }
        MouseArea {
            anchors.fill: parent
            drag.target: root
            drag.minimumX: 0; drag.minimumY: 0
            drag.maximumX: root.parent ? root.parent.width - 80 : 0
            drag.maximumY: root.parent ? root.parent.height - 40 : 0
            cursorShape: Qt.SizeAllCursor
        }
        Row {
            anchors.left: parent.left
            anchors.leftMargin: Theme.spLoose
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spSnug
            Icon { name: "sparkle"; tone: "accent"; size: 20; anchors.verticalCenter: parent.verticalCenter }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                Text { text: "AI Gen"
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontLabel; font.weight: Font.DemiBold; color: Theme.textPrimary }
                Item {                  // provider and model: click to switch the model without opening the settings
                    id: modelChip
                    objectName: "aiModelChip"
                    width: Math.min(250, chipRow.width + 8); height: 24
                    activeFocusOnTab: true
                    Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) root.openQuickPicker(); e.accepted = act }
                    Rectangle { anchors.fill: parent; radius: Theme.radiusControl; color: chipMouse.containsMouse || quick.visible ? "#c8ccd0" : "transparent"
                        border.width: modelChip.activeFocus ? 2 : 0; border.color: Theme.primary }
                    Row { id: chipRow; x: 4; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                        Text { objectName: "aiSubtitle"; text: root.svc ? root.svc.subtitle : "Claude \· claude-sonnet-5-5"
                            width: Math.min(implicitWidth, 215); elide: Text.ElideRight
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
                        Icon { name: "chevron"; size: 10; anchors.verticalCenter: parent.verticalCenter }
                    }
                    MouseArea { id: chipMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.openQuickPicker() }
                    ToolTip.visible: chipMouse.containsMouse && !quick.visible; ToolTip.delay: 500; ToolTip.text: "Switch model"
                }
            }
        }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: Theme.spTight
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Rectangle {              // three-dot menu
                id: dots
                objectName: "aiMenuButton"
                width: 28; height: 28; radius: Theme.radiusControl
                color: dotMouse.containsMouse || menu.visible ? "#c8ccd0" : "transparent"
                border.width: activeFocus ? 2 : 0
                border.color: Theme.primary
                activeFocusOnTab: true
                Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) menu.open(); e.accepted = act }
                Column {
                    anchors.centerIn: parent
                    spacing: 3
                    Repeater { model: 3; delegate: Rectangle { width: 4; height: 4; radius: 2; color: Theme.textPrimary } }
                }
                MouseArea { id: dotMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: menu.open() }
                ToolTip.visible: dotMouse.containsMouse && !menu.visible
                ToolTip.delay: 500
                ToolTip.text: "Menu"
            }
            Rectangle {
                objectName: "aiCloseButton"
                width: 28; height: 28; radius: Theme.radiusControl
                color: closeMouse.containsMouse ? "#c8ccd0" : "transparent"
                border.width: activeFocus ? 2 : 0
                border.color: Theme.primary
                activeFocusOnTab: true
                Keys.onPressed: function (e) { var act = e.key === Qt.Key_Space || e.key === Qt.Key_Return; if (act) root.closeRequested(); e.accepted = act }
                Icon { anchors.centerIn: parent; name: "close"; size: 16 }
                MouseArea { id: closeMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.closeRequested() }
                ToolTip.visible: closeMouse.containsMouse
                ToolTip.delay: 500
                ToolTip.text: "Close (Esc)"
            }
        }
    }

    DropMenu {
        id: menu
        objectName: "aiMenu"
        x: root.width - width - Theme.spTight
        y: bar.height
        width: 220
        items: [ { text: "Settings...", key: "settings" }, { text: "New chat", key: "new" }, { sep: true },
                 { text: "Remove saved API key", key: "clearkey" } ]
        onTriggered: function (key) {
            if (key === "settings") root.settingsOpen = true
            else if (key === "new") { if (root.svc) root.svc.newChat() }
            else if (key === "clearkey") { if (root.svc) root.svc.removeKey(root.svc.provider) }
        }
    }

    // ---- quick model picker (header): pick or type a model for the current provider, nothing else
    function openQuickPicker() {
        if (!root.svc || !root.svc.ready) return
        root.svc.fetchModels(root.svc.provider, root.svc.baseUrl, "")
        quick.open()
        quickPicker.setText(root.svc.model)
    }
    Popup {
        id: quick
        objectName: "aiQuickPicker"
        x: Theme.spBase; y: bar.height + 2
        width: root.width - 2 * Theme.spBase
        padding: Theme.spLoose
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: Theme.panelAlt; border.width: 1; border.color: Theme.fieldBorder; radius: Theme.radiusPanel }
        contentItem: Column {
            spacing: Theme.spSnug
            Text { text: "Model"
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary }
            ModelPicker {
                id: quickPicker
                width: quick.availableWidth
                alwaysOpen: true
                value: root.svc ? root.svc.model : ""
                choices: root.svc ? (root.svc.modelsVersion >= 0 ? root.svc.modelsFor(root.svc.provider) : []) : []
                loading: !!(root.svc && root.svc.fetching)
                onAccepted: function (modelId) { if (root.svc) root.svc.setModel(modelId); quick.close() }
                onRefreshRequested: if (root.svc) root.svc.fetchModels(root.svc.provider, root.svc.baseUrl, "")
            }
            Text {
                visible: !!(root.svc && root.svc.modelWarning(root.svc.provider, quickPicker.typed) !== "")
                width: quick.availableWidth
                text: root.svc ? root.svc.modelWarning(root.svc.provider, quickPicker.typed) : ""
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.warnText
            }
            Text {
                readonly property string link: "<a href=\"settings\" style=\"color:" + Theme.primaryText + "\">Change provider or API key...</a>"
                text: link; textFormat: Text.RichText; height: 24; verticalAlignment: Text.AlignVCenter
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                onLinkActivated: { quick.close(); root.settingsOpen = true }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor }
            }
        }
    }

    // ---- settings (shown automatically the first time, then from the three-dot menu)
    AiSettings {
        id: settings
        visible: root.settingsOpen
        anchors.top: bar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        svc: root.svc
        firstRun: root.svc ? !root.svc.ready : false
        onDone: function (saved) {
            root.settingsOpen = false
            if (!saved && firstRun) root.closeRequested()
            else if (saved) input.forceActiveFocus()
        }
    }

    // ---- conversation
    Item {
        id: chat
        visible: root.hasKey && !root.settingsOpen
        anchors.top: bar.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom

        ListView {
            id: list
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: inputBox.top
            anchors.margins: Theme.spBase
            clip: true
            spacing: Theme.spBase
            model: root.svc ? root.svc.messageCount : root.msgs.length
            property bool stick: true
            onMovingChanged: if (!moving) stick = atYEnd
            onContentHeightChanged: if (stick) Qt.callLater(positionViewAtEnd)
            ScrollBar.vertical: ScrollBar { }

            header: Item { width: list.width; height: root.msgs.length === 0 ? welcome.height : 0
                Column {
                    id: welcome
                    visible: root.msgs.length === 0
                    width: parent.width
                    spacing: Theme.spSnug
                    Text {
                        width: parent.width
                        text: "What should the flow do?"
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSubtitle; font.weight: Font.DemiBold; color: Theme.textPrimary
                    }
                    Text {
                        width: parent.width
                        text: "Describe the inspection in plain words. For example:"
                        wrapMode: Text.WordWrap
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary
                    }
                    Repeater {
                        model: [ "Check the PCB for scratches and fail when any are found",
                                 "Measure the width between two edges and pass if it is 20 to 60 px",
                                 "Count the bright blobs after smoothing and noise removal",
                                 "Make sure the label reads SN- and report green coverage over 5%" ]
                        delegate: Rectangle {
                            width: welcome.width; height: ex.implicitHeight + 14; radius: Theme.radiusPanel
                            color: exm.containsMouse ? Theme.accentDim : Theme.panelAlt
                            border.width: 1; border.color: Theme.fieldBorder
                            Text { id: ex; x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter
                                text: modelData; wrapMode: Text.WordWrap
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                            MouseArea { id: exm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: { input.text = modelData; input.forceActiveFocus() } }
                        }
                    }
                }
            }

            delegate: Item {
                id: msgItem
                readonly property var m: root.msgs[index] || ({ role: "assistant", text: "", tools: [], error: "", flowIndex: -1 })
                readonly property bool mine: m.role === "user"
                width: list.width
                height: bubble.height

                Rectangle {
                    id: bubble
                    anchors.right: msgItem.mine ? parent.right : undefined
                    anchors.left: msgItem.mine ? undefined : parent.left
                    width: msgItem.mine ? parent.width - 40 : parent.width
                    height: col.height + 16
                    radius: Theme.radiusPanel
                    color: msgItem.mine ? Theme.accentDim : Theme.panelAlt
                    border.width: 1
                    border.color: msgItem.mine ? Theme.accentBorder : Theme.fieldBorder

                    Column {
                        id: col
                        x: 12; y: 8
                        width: parent.width - 24
                        spacing: Theme.spSnug

                        Text {
                            text: msgItem.mine ? "You" : "AI Gen"
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; font.weight: Font.DemiBold
                            color: msgItem.mine ? Theme.accentBorder : Theme.primaryText
                        }
                        // what the assistant looked up (visible work, not a black box)
                        Repeater {
                            model: msgItem.m.tools || []
                            delegate: Row {
                                spacing: Theme.spSnug
                                Text { text: modelData.ok ? "✓" : "!"; color: modelData.ok ? Theme.okText : Theme.warnText
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; font.weight: Font.DemiBold }
                                Text { text: modelData.summary; width: col.width - 20; elide: Text.ElideRight
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
                            }
                        }
                        TextEdit {
                            id: userText
                            width: col.width
                            visible: text !== ""
                            text: msgItem.m.text || ""
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.Wrap
                            textFormat: msgItem.mine ? TextEdit.PlainText : TextEdit.MarkdownText
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody
                            color: Theme.textPrimary
                        }
                        Text {
                            visible: msgItem.m.role === "assistant" && root.busy && index === root.msgs.length - 1 && !msgItem.m.text && !msgItem.m.error
                            text: "Working…"
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted
                        }
                        Text {
                            visible: (msgItem.m.error || "") !== ""
                            width: parent.width
                            text: msgItem.m.error || ""
                            wrapMode: Text.WordWrap
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.errorText
                        }

                        // the proposed flow
                        Rectangle {
                            id: flowCard
                            visible: msgItem.m.flow !== undefined
                            width: parent.width
                            height: visible ? fcol.height + 20 : 0
                            radius: Theme.radiusPanel
                            color: Theme.panel
                            border.width: 1; border.color: Theme.accent
                            Column {
                                id: fcol
                                x: 10; y: 10
                                width: parent.width - 20
                                spacing: Theme.spSnug
                                Text {
                                    width: parent.width
                                    text: msgItem.m.flow ? msgItem.m.flow.summary : ""
                                    wrapMode: Text.WordWrap
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary
                                }
                                Text {
                                    text: msgItem.m.flow ? msgItem.m.flow.modules + " modules, " + msgItem.m.flow.links + " links" : ""
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted
                                }
                                Flow {
                                    width: parent.width
                                    spacing: Theme.spTight
                                    Repeater {
                                        model: msgItem.m.flow ? msgItem.m.flow.names : []
                                        delegate: Rectangle {
                                            width: chipText.implicitWidth + 12; height: 20; radius: Theme.radiusControl
                                            color: Theme.panelHeader
                                            Text { id: chipText; anchors.centerIn: parent; text: modelData
                                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textPrimary }
                                        }
                                    }
                                }
                                Text {
                                    visible: !!(msgItem.m.flow && msgItem.m.flow.sideEffects.length > 0)
                                    width: parent.width
                                    text: msgItem.m.flow ? "Review before running: " + msgItem.m.flow.sideEffects.join(", ") + " can contact other systems, write files or run code." : ""
                                    wrapMode: Text.WordWrap
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.warnText
                                }
                                Text {
                                    visible: !!(msgItem.m.flow && msgItem.m.flow.warnings.length > 0)
                                    width: parent.width
                                    text: msgItem.m.flow ? msgItem.m.flow.warnings.join("\n") : ""
                                    wrapMode: Text.WordWrap
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted
                                }
                                Row {
                                    spacing: Theme.spSnug
                                    visible: !!(msgItem.m.flow && !msgItem.m.flow.applied)
                                    AppButton { objectName: "aiAddFlow"; text: "Add as new flow"; kind: "primary"; width: 130
                                        onClicked: if (root.svc) root.svc.applyFlow(msgItem.m.flowIndex, "new") }
                                    AppButton { text: "Replace open flow"; width: 130
                                        onClicked: if (root.svc) root.svc.applyFlow(msgItem.m.flowIndex, "replace") }
                                }
                                Text {
                                    visible: !!(msgItem.m.flow && msgItem.m.flow.applied)
                                    text: "✓ Added to the project (Ctrl+Z undoes it)"
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.okText
                                }
                                Row {
                                    spacing: Theme.spSnug
                                    AppButton { text: "Copy XML"; icon: "copy"; width: 110; onClicked: if (root.svc) root.svc.copyXml(msgItem.m.flowIndex) }
                                    AppButton { text: "Save XML..."; icon: "download"; width: 110
                                        onClicked: { saveXmlDialog.flowIndex = msgItem.m.flowIndex; saveXmlDialog.open() } }
                                }
                            }
                        }
                    }
                }
            }
        }

        // ---- input
        Rectangle {
            id: inputBox
            anchors.bottom: footer.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: Theme.spBase
            height: Math.min(120, Math.max(56, input.contentHeight + 16))
            radius: Theme.radiusPanel
            color: Theme.fieldBg
            border.width: input.activeFocus ? 2 : 1
            border.color: input.activeFocus ? Theme.primary : Theme.fieldBorder
            Flickable {
                id: flick
                anchors.fill: parent
                anchors.leftMargin: Theme.spBase
                anchors.rightMargin: 44
                anchors.topMargin: Theme.spSnug
                anchors.bottomMargin: Theme.spSnug
                contentWidth: width
                contentHeight: input.contentHeight
                clip: true
                TextEdit {
                    id: input
                    objectName: "aiInput"
                    width: flick.width
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    activeFocusOnTab: true
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody
                    color: Theme.textPrimary
                    selectionColor: Theme.primary
                    readOnly: root.busy
                    Keys.onPressed: function (e) {
                        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) {
                            root.submit(); e.accepted = true
                        } else if (e.key === Qt.Key_Escape) {
                            if (root.busy && root.svc) root.svc.stop()
                            else root.closeRequested()
                            e.accepted = true
                        }
                    }
                    Text {
                        visible: input.text.length === 0
                        text: root.busy ? "Working..." : "Describe the flow you want (Enter sends, Shift+Enter adds a line)"
                        font: input.font; color: Theme.textMuted
                    }
                }
            }
            Rectangle {
                id: sendBtn
                objectName: "aiSend"
                anchors.right: parent.right; anchors.rightMargin: 6
                anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                width: 32; height: 32; radius: Theme.radiusPanel
                color: root.busy ? Theme.stopRed : (input.text.trim() === "" ? Theme.buttonBg : Theme.primary)
                Icon { anchors.centerIn: parent; name: root.busy ? "stop" : "send"; tone: input.text.trim() === "" && !root.busy ? "dark" : "white"; size: 16 }
                MouseArea {
                    anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                    onClicked: root.busy ? (root.svc && root.svc.stop()) : root.submit()
                }
                ToolTip.visible: sendMouse.containsMouse
                ToolTip.text: root.busy ? "Stop" : "Send"
                MouseArea { id: sendMouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            }
        }
        Text {
            id: footer
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: Theme.spBase
            anchors.leftMargin: 28                       // clear of the resize grip
            height: 20
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: root.svc ? "AI-generated flows can be wrong: review them before running.   " + (root.svc.tokens.input + root.svc.tokens.output > 0
                  ? (root.svc.tokens.input + root.svc.tokens.output) + " tokens used" : "") : ""
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted
        }
    }

    function submit() {
        if (!root.svc || root.busy || input.text.trim() === "") return
        root.svc.send(input.text)
        input.text = ""
        list.stick = true
    }
    onVisibleChanged: if (visible) {
        if (svc && !svc.ready) settingsOpen = true               // first time: ask for the provider and key
        Qt.callLater(function () { if (hasKey && !settingsOpen) input.forceActiveFocus(); else trap.focusFirst() })
    }

    FileDialog {
        id: saveXmlDialog
        property int flowIndex: -1
        title: "Save flow XML"
        fileMode: FileDialog.SaveFile
        nameFilters: ["XML flow files (*.xml)"]
        defaultSuffix: "xml"
        onAccepted: if (root.svc) root.svc.saveXml(flowIndex, selectedFile.toString())
    }

    // ---- resize grip (lower-left corner; the panel is anchored to the right edge of the workspace)
    MouseArea {
        id: grip
        width: 24; height: 24
        anchors.left: parent.left; anchors.bottom: parent.bottom
        cursorShape: Qt.SizeBDiagCursor
        property real startX; property real startW; property real startH; property real startY
        onPressed: function (m) { var p = mapToItem(root.parent, m.x, m.y); startX = p.x; startY = p.y; startW = root.width; startH = root.height }
        onPositionChanged: function (m) {
            if (!pressed) return
            var p = mapToItem(root.parent, m.x, m.y)
            var nw = Math.max(340, Math.min(760, startW - (p.x - startX)))
            root.x += root.width - nw
            root.width = nw
            root.height = Math.max(380, Math.min(root.parent.height - root.y - 8, startH + (p.y - startY)))
        }
        Canvas {
            anchors.fill: parent
            onPaint: { var c = getContext("2d"); c.strokeStyle = "" + Theme.textMuted; c.lineWidth = 1
                c.beginPath(); c.moveTo(6, 8); c.lineTo(16, 18); c.moveTo(6, 14); c.lineTo(10, 18); c.stroke() }
        }
    }
}
