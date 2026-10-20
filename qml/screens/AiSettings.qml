import QtQuick 2.15
import QtQuick.Controls 2.15
import ApexTheme 1.0
import ApexComponents 1.0

/*
 * AI Gen settings: provider, server address, API key and model (like the model settings of Continue, Cline or
 * Open WebUI).  Shown automatically the first time AI Gen opens, and from the three-dot menu afterwards.
 */
Rectangle {
    id: root
    objectName: "aiSettings"
    property var svc: null
    property bool firstRun: false                    // nothing is configured yet: Cancel closes AI Gen itself
    signal done(bool saved)

    readonly property var providers: svc ? svc.providerList : SampleData.aiProviders
    property int pIndex: 0
    readonly property var cur: providers[Math.min(pIndex, providers.length - 1)]
    property string fetchedFor: ""
    readonly property var modelChoices: {
        var ids = [], labels = []
        for (var i = 0; i < cur.models.length; i++) { ids.push(cur.models[i].id); labels.push(cur.models[i].label) }
        if (svc && fetchedFor === cur.id)
            for (var j = 0; j < svc.fetchedModels.length; j++)
                if (ids.indexOf(svc.fetchedModels[j]) < 0) { ids.push(svc.fetchedModels[j]); labels.push(svc.fetchedModels[j]) }
        return { ids: ids, labels: labels }
    }

    color: Theme.panel

    function load(providerId) {
        for (var i = 0; i < providers.length; i++) if (providers[i].id === providerId) pIndex = i
        baseUrlField.text = svc ? svc.savedBaseUrlFor(cur.id) : cur.baseUrl
        modelField.text = svc ? svc.savedModelFor(cur.id) : (cur.models.length ? cur.models[0].id : "")
        keyField.text = ""
        if (svc) svc.clearError()
    }
    onVisibleChanged: if (visible) { load(svc ? svc.provider : "anthropic"); fetchedFor = "" }

    function save() {
        if (!svc) { done(true); return }
        if (svc.saveSettings(cur.id, baseUrlField.text, modelField.text, keyField.text, rememberBox.checked)) done(true)
    }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.bottomMargin: footer.height
        contentWidth: width
        contentHeight: form.height + 2 * Theme.spSection
        clip: true
        ScrollBar.vertical: ScrollBar { }

        Column {
            id: form
            x: Theme.spSection; y: Theme.spSection
            width: flick.width - 2 * Theme.spSection
            spacing: Theme.spBase

            Text {
                width: parent.width
                text: root.firstRun ? "Set up AI Gen" : "AI Gen settings"
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSubtitle; font.weight: Font.DemiBold; color: Theme.textPrimary
            }
            Text {
                visible: root.firstRun
                width: parent.width
                text: "Choose the AI provider and enter your API key. Your key stays on this computer and is sent only to the provider you pick."
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary
            }

            SectionLabel { width: parent.width; text: "Provider" }
            SelectBox {
                id: providerBox
                objectName: "aiProvider"
                width: parent.width
                model: root.providers.map(function (p) { return p.label })
                currentIndex: root.pIndex
                onActivated: function (i) { root.load(root.providers[i].id); root.fetchedFor = "" }
            }

            Column {
                width: parent.width
                spacing: Theme.spTight
                visible: root.cur.editableUrl
                SectionLabel { width: parent.width; text: root.cur.id === "custom" ? "Server address (OpenAI-compatible)" : "Server address" }
                TextBox { id: baseUrlField; objectName: "aiBaseUrl"; width: parent.width; placeholder: "https://host/v1" }
            }

            SectionLabel { width: parent.width; text: "API key" + (root.cur.needsKey ? "" : " (optional)") }
            TextBox {
                id: keyField
                objectName: "aiKeyField"
                width: parent.width
                placeholder: root.cur.keyPlaceholder
                echoMode: showKey.checked ? TextInput.Normal : TextInput.Password
                onAccepted: root.save()
            }
            Row {
                spacing: Theme.spLoose
                CheckLabel { id: showKey; objectName: "aiShowKey"; text: "Show key" }
                CheckLabel {
                    id: rememberBox
                    objectName: "aiRemember"
                    visible: !!(root.svc && root.svc.canRemember)
                    text: "Remember on this computer"
                }
            }
            Text {
                readonly property string hint: root.svc ? root.svc.keyHintFor(root.cur.id) : ""
                visible: hint !== "" && keyField.text === ""
                width: parent.width
                text: "A key is already set (" + hint + (root.svc && root.svc.keySourceFor(root.cur.id) === "environment" ? ", from the environment variable"
                      : root.svc && root.svc.keySourceFor(root.cur.id) === "saved" ? ", saved on this computer" : ", this session") + "). Leave the field empty to keep it."
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.okText
            }
            Text {
                visible: !!(root.svc && !root.svc.canRemember)
                width: parent.width
                text: "No credential store is available, so the key is kept for this session only."
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted
            }
            Text {
                visible: root.cur.keyUrl !== ""
                text: "<a href=\"" + root.cur.keyUrl + "\" style=\"color:" + Theme.primaryText + "\">" + (root.cur.needsKey ? "Get an API key" : "Get " + root.cur.label.split(" (")[0]) + "</a>"
                textFormat: Text.RichText
                linkColor: Theme.primaryText
                onLinkActivated: function (link) { Qt.openUrlExternally(link) }
                height: 24
                verticalAlignment: Text.AlignVCenter
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor }
            }

            SectionLabel { width: parent.width; text: "Model" }
            Row {
                width: parent.width
                spacing: Theme.spSnug
                SelectBox {
                    id: modelBox
                    objectName: "aiModelList"
                    width: parent.width - fetchBtn.width - Theme.spSnug
                    model: root.modelChoices.labels.length ? root.modelChoices.labels : ["(type a model id below)"]
                    currentIndex: Math.max(0, root.modelChoices.ids.indexOf(modelField.text))
                    onActivated: function (i) { if (root.modelChoices.ids.length) modelField.text = root.modelChoices.ids[i] }
                }
                AppButton {
                    id: fetchBtn
                    objectName: "aiFetchModels"
                    text: root.svc && root.svc.fetching ? "Loading..." : "Fetch list"
                    width: 96
                    enabledState: !!(root.svc && !root.svc.fetching)
                    onClicked: { root.fetchedFor = root.cur.id; root.svc.fetchModels(root.cur.id, baseUrlField.text, keyField.text) }
                }
            }
            TextBox { id: modelField; objectName: "aiModelField"; width: parent.width; placeholder: "or type any model id" }

            Row {
                spacing: Theme.spBase
                AppButton {
                    objectName: "aiTest"
                    text: "Test connection"
                    width: 130
                    enabledState: !!(root.svc && root.svc.testState !== "testing")
                    onClicked: root.svc.testConnection(root.cur.id, baseUrlField.text, modelField.text, keyField.text)
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !!(root.svc && root.svc.testState !== "")
                    width: form.width - 140
                    text: root.svc ? (root.svc.testState === "ok" ? "✓ " : root.svc.testState === "error" ? "! " : "") + root.svc.testMessage : ""
                    wrapMode: Text.WordWrap
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                    color: root.svc && root.svc.testState === "ok" ? Theme.okText : root.svc && root.svc.testState === "error" ? Theme.errorText : Theme.textMuted
                }
            }
            Text {
                visible: !!(root.svc && root.svc.settingsError !== "")
                width: parent.width
                text: root.svc ? root.svc.settingsError : ""
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.errorText
            }
            Text {
                width: parent.width
                text: "Requests go straight from this computer to the provider and are billed to your account there. Flows the assistant works on (module names, parameters, links) are sent; images never are. Local models (Ollama, LM Studio) stay on this computer."
                wrapMode: Text.WordWrap
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted
            }
        }
    }

    Rectangle {
        id: footer
        anchors.bottom: parent.bottom
        width: parent.width
        height: 52
        color: Theme.panel
        Rectangle { width: parent.width; height: 1; color: Theme.fieldBorder }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: Theme.spSection
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spBase
            AppButton { objectName: "aiCancel"; text: "Cancel"; width: 90; onClicked: root.done(false) }
            AppButton { objectName: "aiSave"; text: root.firstRun ? "Save and start" : "Save"; kind: "primary"; width: 130; onClicked: root.save() }
        }
    }
}
