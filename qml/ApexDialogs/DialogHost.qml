import QtQuick 2.15

/*
 * Holds every dialog of the application.  Each one is a normal item (hidden until shown), so
 * Qt Design Studio lists them all in the Navigator and you can edit them visually.
 *
 *   dialogs.show("globalVars")                      // by name
 *   dialogs.showInfo("About", "Apex Vision Studio") // message box
 *   dialogs.showModule("node_id", "02 IC Alignment")
 */
Item {
    id: host
    property string current: ""
    visible: current !== ""
    signal projectCreated()

    function show(name) { current = name }
    function showInfo(title, text) { info.heading = title; info.message = text; current = "info" }
    function showModule(id, name) { moduleConfig.nodeId = id; moduleConfig.moduleName = name; current = "moduleConfig" }
    function showRename(id, name, tool) { rename.nodeId = id; rename.currentName = name; rename.toolName = tool; current = "rename" }
    function showPlugins(tab) { plugins.tab = tab; current = "plugins" }
    function close() { current = "" }

    InfoDialog { id: info; anchors.fill: parent; visible: host.current === "info"; onClosed: host.close() }
    GlobalVariablesDialog { anchors.fill: parent; visible: host.current === "globalVars"; onClosed: host.close() }
    FlowSettingsDialog { anchors.fill: parent; visible: host.current === "flowSettings"; onClosed: host.close() }
    ValidationDialog { anchors.fill: parent; visible: host.current === "validation"; onClosed: host.close() }
    ModuleConfigDialog { id: moduleConfig; anchors.fill: parent; visible: host.current === "moduleConfig"; onClosed: host.close() }
    CameraSetDialog { anchors.fill: parent; visible: host.current === "cameraSet"; onClosed: host.close()
        onLensCalibrationRequested: host.current = "lensCal" }
    LensCalibrationDialog { anchors.fill: parent; visible: host.current === "lensCal"; onClosed: host.close() }
    PluginManagerDialog { id: plugins; anchors.fill: parent; visible: host.current === "plugins"; onClosed: host.close() }
    NewProjectDialog { anchors.fill: parent; visible: host.current === "newProject"; onClosed: host.close()
        onCreated: { host.close(); host.projectCreated() } }
    RenameDialog { id: rename; anchors.fill: parent; visible: host.current === "rename"; onClosed: host.close() }
    ConfirmDialog { id: confirm; anchors.fill: parent; visible: host.current === "confirm"; onClosed: host.close() }

    // the backend asks before unsaved edits would be replaced
    Connections {
        target: typeof appBackend !== "undefined" ? appBackend : null
        ignoreUnknownSignals: true
        function onConfirmRequested(text) { confirm.message = text; host.current = "confirm" }
    }
}
