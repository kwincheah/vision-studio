import QtQuick 2.15
import QtQuick.Dialogs
import ApexTheme 1.0
import ApexComponents 1.0

// Plugin manager: installed plugins, community marketplace, GitHub installer, plugin creator.
// Live through `appPlugins` (vm_clone/qml_services.py); sample data in Qt Design Studio.
DialogFrame {
    id: root
    readonly property var service: typeof appPlugins !== "undefined" ? appPlugins : null
    readonly property var installed: service ? service.installed : SampleData.plugins
    readonly property var market: service ? service.marketplace : SampleData.marketplace
    readonly property string log: service ? service.log : "Installation log appears here."
    readonly property bool busy: service ? service.busy : false
    property int tab: 0
    title: "Plugin Manager"
    dialogWidth: 880
    dialogHeight: 580

    function detail() {
        var t = installedTable.currentRow
        if (t < 0 || t >= installed.length) return installed.length ? "Select a plugin to see its tools." : "No third-party plugins loaded."
        return installed[t].detail !== undefined ? installed[t].detail : installed[t].name
    }

    FolderDialog { id: pluginFolder; title: "Plugin folder"; onAccepted: if (root.service) root.service.loadFolder(selectedFolder.toString()) }
    FolderDialog { id: packageFolder; title: "Plugin folder to package"; onAccepted: if (root.service) root.service.package(selectedFolder.toString()) }
    FolderDialog { id: scaffoldFolder; title: "Create the plugin in..."; onAccepted: {
        if (root.service) root.service.scaffold(selectedFolder.toString(), idField.text, nameField.text, authorField.text,
                                                categoryField.text, toolField.text, descField.text) } }

    Column {
        anchors.fill: parent
        spacing: 0
        Row {
            Repeater {
                model: ["Installed Plugins", "Community Marketplace", "Install from GitHub", "Create & Publish"]
                delegate: TabButton2 { text: modelData; selected: root.tab === index; onClicked: root.tab = index }
            }
        }
        Rectangle {
            width: parent.width; height: parent.height - 26
            color: Theme.panelAlt; border.width: 1; border.color: "#c0c4c8"

            // ---- installed
            Row {
                anchors.fill: parent; anchors.margins: 12; spacing: 12
                visible: root.tab === 0
                Column { width: parent.width * 0.58; height: parent.height; spacing: 8
                    DataTable { id: installedTable; width: parent.width; height: parent.height - 40
                        columns: [ { title: "Plugin Name", key: "name", width: 0 }, { title: "Version", key: "version", width: 70 }, { title: "Category", key: "category", width: 110 }, { title: "Status", key: "status", width: 70 } ]
                        rows: root.installed }
                    Row { spacing: 8
                        AppButton { text: "Load from Folder..."; width: 140; onClicked: pluginFolder.open() }
                        AppButton { text: "Rescan"; width: 90; onClicked: if (root.service) root.service.rescan() }
                        AppButton { text: "Unload"; width: 90
                            onClicked: if (root.service && installedTable.currentRow >= 0) root.service.unload(root.installed[installedTable.currentRow].id) }
                        AppButton { text: "Package .vmpkg"; width: 120; onClicked: packageFolder.open() } }
                }
                Column { width: parent.width * 0.42 - 12; height: parent.height; spacing: 8
                    SectionLabel { width: parent.width; text: "Plugin Details & Exported Tools" }
                    Rectangle { width: parent.width; height: parent.height - 30; color: "#c0c4c8"; radius: 4
                        Text { x: 10; y: 10; width: parent.width - 20; wrapMode: Text.WordWrap
                            text: { installedTable.currentRow; return root.detail() }
                            font.family: Theme.monoFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary } }
                }
            }
            // ---- marketplace
            Column {
                anchors.fill: parent; anchors.margins: 12; spacing: 8
                visible: root.tab === 1
                Row { spacing: 8
                    TextBox { id: search; width: 320; placeholder: "Search community plugins..." }
                    AppButton { text: "Refresh Catalog"; width: 130; onClicked: if (root.service) root.service.rescan() } }
                DataTable { id: marketTable; width: parent.width; height: parent.height - 80
                    columns: [ { title: "Plugin", key: "name", width: 0 }, { title: "Author", key: "author", width: 130 }, { title: "Version", key: "version", width: 80 }, { title: "Status", key: "status", width: 90 } ]
                    rows: { var f = search.text.toLowerCase(), out = []
                            for (var i = 0; i < root.market.length; i++) if (f === "" || root.market[i].name.toLowerCase().indexOf(f) >= 0) out.push(root.market[i])
                            return out } }
                Row { spacing: 8
                    AppButton { text: "Install Selected"; kind: "primary"; width: 140; enabledState: !root.busy && marketTable.currentRow >= 0
                        onClicked: if (root.service) root.service.installMarketplace(marketTable.rows[marketTable.currentRow].id) }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: root.busy ? "Working..." : ""; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted } }
            }
            // ---- github
            Column {
                anchors.fill: parent; anchors.margins: 14; spacing: 12
                visible: root.tab === 2
                FormRow { width: parent.width; label: "Repository URL"; TextBox { id: repoField; width: parent.width; placeholder: "https://github.com/owner/repo" } }
                FormRow { width: 260; label: "Branch"; TextBox { id: branchField; width: 260; text: "main" } }
                AppButton { text: root.busy ? "Working..." : "Download, Validate && Install"; kind: "primary"; width: 230; enabledState: !root.busy
                    onClicked: if (root.service) root.service.installGithub(repoField.text, branchField.text) }
                Rectangle { width: parent.width; height: parent.height - 190; color: "#c0c4c8"; radius: 4; clip: true
                    Text { x: 10; y: 10; width: parent.width - 20; wrapMode: Text.WordWrap; text: root.log; font.family: Theme.monoFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary } }
            }
            // ---- creator
            Column {
                anchors.fill: parent; anchors.margins: 14; spacing: 10
                visible: root.tab === 3
                Text { width: parent.width; wrapMode: Text.WordWrap; text: "Scaffold a complete, ready-to-publish plugin repository: plugin.json, a typed PluginToolBase template, README.md and .gitignore."
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                SectionLabel { width: parent.width; text: "Plugin Specification" }
                Grid { columns: 2; columnSpacing: 14; rowSpacing: 8
                    Text { width: 130; height: 26; verticalAlignment: Text.AlignVCenter; text: "Plugin ID:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                    TextBox { id: idField; width: 280; text: "my_custom_filter" }
                    Text { width: 130; height: 26; verticalAlignment: Text.AlignVCenter; text: "Package Name:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                    TextBox { id: nameField; width: 280; text: "Adaptive Blur Filter" }
                    Text { width: 130; height: 26; verticalAlignment: Text.AlignVCenter; text: "Author / Org:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                    TextBox { id: authorField; width: 280; text: "Developer" }
                    Text { width: 130; height: 26; verticalAlignment: Text.AlignVCenter; text: "Category:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                    TextBox { id: categoryField; width: 280; text: "Custom Filters" }
                    Text { width: 130; height: 26; verticalAlignment: Text.AlignVCenter; text: "Primary Tool Name:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                    TextBox { id: toolField; width: 280; text: "Adaptive Blur" }
                    Text { width: 130; height: 26; verticalAlignment: Text.AlignVCenter; text: "Description:"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                    TextBox { id: descField; width: 280; text: "High performance spatial adaptive filtering tool." }
                }
                AppButton { text: "Generate Plugin Scaffold..."; kind: "primary"; width: 220; onClicked: scaffoldFolder.open() }
                Text { width: parent.width; wrapMode: Text.WordWrap; text: root.log; font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
            }
        }
    }
    buttons: [ AppButton { text: "Close"; width: 90; onClicked: root.closed() } ]
}
