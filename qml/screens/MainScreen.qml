import QtQuick 2.15
import QtQuick.Shapes 1.15
import QtQuick.Controls 2.15
import ApexTheme 1.0
import ApexComponents 1.0
import ApexDialogs 1.0
import QtQuick.Dialogs

/*
 * Main workspace: menu bar, toolbars, tool rail, flow canvas, image viewer, results.
 * Every visual is a component from ApexComponents; every colour comes from Theme.
 * Data comes from the Python backend when it is present, otherwise from SampleData.
 */
Rectangle {
    id: root
    width: 1600
    height: 950
    color: Theme.appBg

    // ---- data (backend when running live, sample data in the design canvas) -------------
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    readonly property string solutionName: backend ? backend.solutionName : SampleData.solutionName
    readonly property bool dirty: backend ? backend.dirty : false
    readonly property string role: backend ? backend.role : "Engineer"
    readonly property var nodes: backend ? backend.nodes : SampleData.nodes
    // The backend hands over a brand-new list on every update. The canvas must not rebuild its cards and wires each time
    // (they flickered, and a drag in progress was destroyed), so the lists the Repeaters use only change when their content does;
    // the cards read their live values (status, time, position) from `nodes` by id.
    property var connections: []
    property var nodeIds: []
    property var groupFrameList: []
    property var tabList: []                  // the flow tabs; replaced only when something in them changed
    readonly property string tabKey: tabList.length + "|" + tabList.map(function (t) { return t.active ? t.name : "" }).join("")
    function cardData(id) {
        for (var i = 0; i < nodes.length; i++) if (nodes[i].id === id) return nodes[i]
        return ({ id: id, title: "", tool: "", status: "PASS", ms: 0, x: 0, y: 0, inputs: [], outputs: [] })
    }
    function steady() {
        var ids = []
        for (var i = 0; i < nodes.length; i++) ids.push(nodes[i].id)
        if (ids.join("|") !== nodeIds.join("|")) nodeIds = ids
        var c = backend ? backend.connections : SampleData.connections
        if (JSON.stringify(c) !== JSON.stringify(connections)) connections = c
        var t = backend ? backend.flowTabs : [{ "name": "Flow1", "verdict": "", "ms": 0, "active": true }]
        if (JSON.stringify(t) !== JSON.stringify(tabList)) tabList = t
        var g = backend ? backend.groupFrames : []
        if (JSON.stringify(g) !== JSON.stringify(groupFrameList)) groupFrameList = g
    }
    onNodesChanged: steady()
    Component.onCompleted: steady()
    readonly property var results: backend ? backend.results : SampleData.results
    readonly property string verdict: backend ? backend.verdict : "FAIL"
    readonly property bool running: backend ? backend.running : false
    readonly property string hint: backend ? backend.hint : "Loaded solution 'PCB_Inspection_Demo' (1 flow(s))"
    readonly property real flowMs: backend ? backend.flowMs : 152.74
    readonly property real algoMs: backend ? backend.algoMs : 152.70
    readonly property int toolCount: nodes.length

    property int workspaceTab: 0              // 0 flow, 1 operation, 2 multi-flow
    property int resultTab: 0
    property string viewTab: "image"          // the top tab pair: "image" or "result"
    readonly property var moduleRows: backend ? backend.moduleResults : []
    readonly property var runHistory: backend ? backend.history : []
    readonly property var helpInfo: backend ? backend.selectedHelp : ({})
    property string selectedNode: nodes.length ? nodes[0].id : ""
    readonly property bool loopOn: backend ? backend.loop : designLoop
    property bool designLoop: false
    function setLoop(on) { if (backend) backend.loop = on; else designLoop = on }
    readonly property bool allLoopOn: backend ? backend.allLoop : false
    function setAllLoop(on) { if (backend) backend.allLoop = on }
    property bool showGrid: true
    readonly property var layers: backend ? backend.layers : ({ overlays: true, rois: true, metrics: true, datums: true, crosshair: false, histogram: false })
    readonly property string formatted: backend ? backend.formattedOutput : "01_ImageAcquisition,OK,Width=800,Height=600"
    // after a project loads, bring clipped modules into view (never zoom in)
    Timer { id: fitTimer; interval: 120; onTriggered: root.fitIfClipped() }
    function fitIfClipped() {
        var right = 0, bottom = 0
        for (var i = 0; i < nodes.length; i++) {
            var p = pos[nodes[i].id]
            if (!p) continue
            right = Math.max(right, p.x + 190); bottom = Math.max(bottom, p.y + 54 + 14 * Math.max(nodes[i].inputs.length, nodes[i].outputs.length, 1))
        }
        if (right * zoom + panX > canvas.width - 10 || bottom * zoom + panY > canvas.height - 10) fitViewTo(1.0)
    }
    Connections {                // a loaded / replaced / edited flow may no longer contain the selected module
        target: root.backend
        ignoreUnknownSignals: true
        function onChanged() { if (root.backend && !root.nodeById(root.selectedNode)) root.selectedNode = root.backend.selectedId }
    }
    Connections {
        target: root.backend
        ignoreUnknownSignals: true
        function onWorkspaceRequested() { root.zoom = 1; root.panX = 0; root.panY = 0; viewport.resetView(); fitTimer.restart() }
    }
    property var pos: ({})                    // node id -> {x, y}, kept live while dragging

    // ---- flow canvas view + wire drag state
    property real zoom: 1.0
    property real panX: 0
    property real panY: 0
    // a wire being dragged: anchored at (from, index) - an output for a normal drag, an input when `reverse`;
    // `relink` is the existing wire being moved; `target` the port it would snap to ({id, index, x, y, ok, reason})
    property var wireDrag: ({ active: false, from: "", index: 0, x: 0, y: 0, reverse: false, relink: null, target: null })
    property var portStates: ({})            // node id -> {inputs: [...], outputs: [...]} of "ok" | "dim" | "hot" while a wire is dragged
    property var wireRings: []               // halos drawn around the ports that can take the dragged wire
    property var hiddenLink: null            // the wire that is being moved (not drawn while it moves)
    property var hoverLink: null
    property real wireCx: 0                  // pointer position in canvas coordinates (auto-pan)
    property real wireCy: 0
    readonly property real snapRadius: 26
    readonly property var roi: backend ? backend.selectedRoi : [300, 250, 200, 100]
    // The selected module's Display Setup (its overlay switches and colour).
    readonly property var displaySetup: backend && backend.selectedDisplay
                                        ? backend.selectedDisplay
                                        : ({ roi: true, labels: true, boxes: true, colour: "#e4b030" })
    // Share of the right column's height given to the image block; the result block below
    // it takes the rest.  0.6 keeps the viewer dominant, as VisionMaster's does.
    readonly property real imageBlockShare: 0.6

    // one wheel notch is 120 units and zooms by 15%; a touchpad sends many small steps, so the factor follows the amount scrolled
    function wheelFactor(w) {
        var d = w.angleDelta.y !== 0 ? w.angleDelta.y : w.pixelDelta.y * 2
        return Math.pow(1.15, Math.max(-480, Math.min(480, d)) / 120)
    }
    function zoomAt(cx, cy, factor) {
        var nz = Math.max(0.25, Math.min(2.5, zoom * factor))
        panX = cx - (cx - panX) * nz / zoom
        panY = cy - (cy - panY) * nz / zoom
        zoom = nz
    }
    function fitView() { fitViewTo(1.5) }
    function fitViewTo(maxZoom) {
        var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9, any = false
        for (var i = 0; i < nodes.length; i++) {
            var p = pos[nodes[i].id]
            if (!p) continue
            any = true
            minX = Math.min(minX, p.x); minY = Math.min(minY, p.y)
            maxX = Math.max(maxX, p.x + 180); maxY = Math.max(maxY, p.y + 54 + 14 * Math.max(nodes[i].inputs.length, nodes[i].outputs.length, 1))
        }
        if (!any) { zoom = 1; panX = 0; panY = 0; return }
        var w = maxX - minX + 80, h = maxY - minY + 80
        zoom = Math.max(0.25, Math.min(maxZoom === undefined ? 1.5 : maxZoom, Math.min(canvas.width / w, canvas.height / h)))
        panX = (canvas.width - (maxX - minX) * zoom) / 2 - minX * zoom
        panY = (canvas.height - (maxY - minY) * zoom) / 2 - minY * zoom
    }
    // ---- link (wire) selection
    property var selectedLink: null           // {from, fromPort, to, toPort} of the highlighted wire
    function sameLink(a, b) {
        return a != null && b != null && a.from === b.from && a.fromPort === b.fromPort && a.to === b.to && a.toPort === b.toPort
    }
    function distToSegment(px, py, ax, ay, bx, by) {
        var dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy
        var t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2))
        var cx = ax + t * dx, cy = ay + t * dy
        return Math.sqrt((px - cx) * (px - cx) + (py - cy) * (py - cy))
    }
    // wires are cubic curves that leave an output to the right and enter an input from the left (as in NodeGraphQt)
    function wireDx(a, b) { return Math.max(50, Math.abs(b.x - a.x) * 0.5) }
    function bezierPoint(a, b, t) {
        var dx = wireDx(a, b), u = 1 - t
        var c1x = a.x + dx, c2x = b.x - dx
        return Qt.point(u * u * u * a.x + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t * t * t * b.x,
                        u * u * u * a.y + 3 * u * u * t * a.y + 3 * u * t * t * b.y + t * t * t * b.y)
    }
    function distToWire(x, y, a, b) {
        var best = 1e9, prev = a
        for (var i = 1; i <= 28; i++) {
            var q = bezierPoint(a, b, i / 28)
            best = Math.min(best, distToSegment(x, y, prev.x, prev.y, q.x, q.y))
            prev = q
        }
        return best
    }
    // the wire under scene point (x, y), or null
    function linkAt(x, y) {
        var tol = 7 / zoom, best = null, bestD = tol
        for (var i = 0; i < connections.length; i++) {
            var c = connections[i]
            if (sameLink(c, hiddenLink)) continue
            var d = distToWire(x, y, portPoint(c.from, c.fromPort, true), portPoint(c.to, c.toPort, false))
            if (d <= bestD) { bestD = d; best = c }
        }
        return best
    }
    function portDtype(id, index, output) {
        var n = nodeById(id)
        if (!n) return ""
        var l = output ? n.outputs : n.inputs
        return index >= 0 && index < l.length ? (l[index].dtype || "") : ""
    }
    function wireColor(c) { return Theme.portColor(portDtype(c.from, c.fromPort, true), "value") }
    // same rule as the engine: ANY fits everything, equal types fit, VALUE and BOOLEAN are interchangeable
    function typesFit(srcDtype, dstDtype) {
        if (srcDtype === "" || dstDtype === "" || srcDtype === "ANY" || dstDtype === "ANY" || srcDtype === dstDtype) return true
        return (srcDtype === "VALUE" || srcDtype === "BOOLEAN") && (dstDtype === "VALUE" || dstDtype === "BOOLEAN")
    }
    function linkedInputs(id) {
        var out = []
        for (var i = 0; i < connections.length; i++) if (connections[i].to === id) out[connections[i].toPort] = true
        return out
    }

    // ---- dragging a wire with the mouse -------------------------------------------------------
    //  from an output: moves to an input.   from a connected input: picks the wire up and moves its end.
    //  from a free input: links backwards to an output.  Ports that fit are ringed, the nearest one snaps.
    function beginWire(id, index, fromOutput, relink) {
        canvas.forceActiveFocus()
        var anchor = portPoint(id, index, fromOutput)
        hiddenLink = relink
        wireDrag = { active: true, from: id, index: index, x: anchor.x, y: anchor.y, reverse: !fromOutput, relink: relink, target: null }
        selectedLink = null
        refreshPortStates()
    }
    function refreshPortStates() {
        var d = wireDrag
        if (!d.active) { portStates = {}; wireRings = []; return }
        var dt = portDtype(d.from, d.index, !d.reverse), st = {}, rings = []
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i]
            if (n.id === d.from) continue
            var ins = [], outs = []
            var list = d.reverse ? n.outputs : n.inputs
            for (var k = 0; k < list.length; k++) {
                var fits = d.reverse ? typesFit(list[k].dtype || "", dt) : typesFit(dt, list[k].dtype || "")
                var hot = d.target && d.target.id === n.id && d.target.index === k
                var state = hot && d.target.ok ? "hot" : (fits ? "ok" : "dim")
                var q = portPoint(n.id, k, d.reverse)
                if (hot) rings.push({ x: q.x, y: q.y, state: d.target.ok ? "hot" : "bad" })
                else if (fits) rings.push({ x: q.x, y: q.y, state: "cand" })
                if (d.reverse) outs[k] = state; else ins[k] = state
            }
            st[n.id] = { inputs: ins, outputs: outs }
        }
        portStates = st
        wireRings = rings
    }
    function targetReason(d, id, index) {
        if (!backend) return ""
        return d.reverse ? backend.canConnect(id, index, d.from, d.index) : backend.canConnect(d.from, d.index, id, index)
    }
    function updateWireTarget(p) {
        var d = wireDrag
        if (!d.active) return
        var best = null, bestDist = snapRadius / Math.max(0.6, zoom)
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i].id === d.from) continue
            var list = d.reverse ? nodes[i].outputs : nodes[i].inputs
            for (var k = 0; k < list.length; k++) {
                var q = portPoint(nodes[i].id, k, d.reverse)
                var dist = Math.sqrt((q.x - p.x) * (q.x - p.x) + (q.y - p.y) * (q.y - p.y))
                if (dist < bestDist) { bestDist = dist; best = { id: nodes[i].id, index: k, x: q.x, y: q.y } }
            }
        }
        if (best === null) {                       // dropped on the body of a module: use its first port that fits (free ones first)
            var dt = portDtype(d.from, d.index, !d.reverse)
            for (var j = 0; j < nodes.length && best === null; j++) {
                var c = cardOf(nodes[j].id)
                if (nodes[j].id === d.from || !c || p.x < c.x || p.x > c.x + c.width || p.y < c.y || p.y > c.y + c.height) continue
                var ports = d.reverse ? nodes[j].outputs : nodes[j].inputs
                var taken = d.reverse ? [] : linkedInputs(nodes[j].id), pick = -1
                for (var m = 0; m < ports.length; m++) {
                    var fits = d.reverse ? typesFit(ports[m].dtype || "", dt) : typesFit(dt, ports[m].dtype || "")
                    if (!fits) continue
                    if (!taken[m]) { pick = m; break }
                    if (pick < 0) pick = m
                }
                if (pick >= 0) {
                    var qq = portPoint(nodes[j].id, pick, d.reverse)
                    best = { id: nodes[j].id, index: pick, x: qq.x, y: qq.y }
                }
            }
        }
        if (best) {
            var why = targetReason(d, best.id, best.index)
            best.ok = why === ""
            best.reason = why
        }
        var old = d.target
        withWire({ target: best })
        if ((old ? old.id + ":" + old.index + ":" + old.ok : "") !== (best ? best.id + ":" + best.index + ":" + best.ok : "")) refreshPortStates()
    }
    function withWire(changes) {                 // a NEW object each time: assigning the same object is not seen as a change
        var d = {}
        for (var k in wireDrag) d[k] = wireDrag[k]
        for (var j in changes) d[j] = changes[j]
        wireDrag = d
    }
    function moveWire(p) {
        var d = wireDrag
        if (!d.active) return
        withWire({ x: p.x, y: p.y })
        var c = scene.mapToItem(canvas, p.x, p.y)
        wireCx = c.x; wireCy = c.y
        updateWireTarget(p)
    }
    function resetWire() {
        wireDrag = { active: false, from: "", index: 0, x: 0, y: 0, reverse: false, relink: null, target: null }
        hiddenLink = null
        refreshPortStates()
    }
    function cancelWire() { resetWire() }
    function endWire(pt) {
        var d = wireDrag
        if (!d.active) return
        var t = d.target
        resetWire()
        if (t && t.ok) {
            if (!backend) { say("Connected (design-time preview)"); return }
            if (d.reverse) backend.connectPorts(t.id, t.index, d.from, d.index)
            else if (d.relink) backend.reconnect(d.from, d.index, d.relink.to, d.relink.toPort, t.id, t.index)
            else backend.connectPorts(d.from, d.index, t.id, t.index)
        } else if (t) {
            say(t.reason || "That wire is not allowed")
        } else if (d.relink) {
            if (backend) backend.reconnect(d.from, d.index, d.relink.to, d.relink.toPort, "", 0)      // dropped on nothing: the wire is removed
            say("Wire removed (Ctrl+Z restores it)")
        } else {
            say(d.reverse ? "Drop the wire on an output port (Esc cancels)" : "Drop the wire on an input port (Esc cancels)")
        }
    }
    function finishWire(pt) { endWire(pt) }
    Timer {                                  // dragging a wire to the edge of the canvas scrolls it
        interval: 30
        running: root.wireDrag.active
        repeat: true
        onTriggered: {
            var m = 36, dx = 0, dy = 0
            if (root.wireCx < m) dx = 12; else if (root.wireCx > canvas.width - m) dx = -12
            if (root.wireCy < m) dy = 12; else if (root.wireCy > canvas.height - m) dy = -12
            if (dx === 0 && dy === 0) return
            root.panX += dx; root.panY += dy
            root.moveWire(Qt.point((root.wireCx - root.panX) / root.zoom, (root.wireCy - root.panY) / root.zoom))
        }
    }

    onConnectionsChanged: {
        if (selectedLink == null) return
        for (var i = 0; i < connections.length; i++) if (sameLink(connections[i], selectedLink)) return
        selectedLink = null
    }
    function deleteSelected() {
        if (selectedLink != null) {
            var l = selectedLink
            selectedLink = null
            if (backend) backend.disconnectInput(l.to, l.toPort); else say("Link deleted")
            return
        }
        if (selectedNode === "") return
        if (backend) backend.deleteNode(selectedNode); else say("Module deleted")
    }
    // ---- keyboard control of the flow canvas ------------------------------------------------
    //  arrows select the neighbouring module      Shift+arrows move it (Alt = fine, 1 px)
    //  Enter configure   F2 rename     K / Shift+K select next / previous link     Delete remove
    //  L start a link from the selected module: [ ] pick its output, arrows pick the target module,
    //    1-9 pick the target input, Enter connects, Esc cancels      + / - zoom      Ctrl+arrows pan
    property var kbWire: ({ active: false, from: "", out: 0, target: "", inp: 0 })
    property bool moveBurst: false
    Timer { id: burstTimer; interval: 700; onTriggered: root.moveBurst = false }

    function cardOf(id) {
        for (var i = 0; i < nodes.length; i++) if (nodes[i].id === id) return nodeRepeater.itemAt(i)
        return null
    }
    function ensureVisible(id) {
        var c = cardOf(id)
        if (!c) return
        var m = 40
        var l = c.x * zoom + panX, t = c.y * zoom + panY, r = (c.x + c.width) * zoom + panX, b = (c.y + c.height) * zoom + panY
        if (l < m) panX += m - l
        else if (r > canvas.width - m) panX -= r - (canvas.width - m)
        if (t < m) panY += m - t
        else if (b > canvas.height - m) panY -= b - (canvas.height - m)
    }
    function selectModule(id) {
        selectedLink = null
        selectedNode = id
        if (backend) backend.selectNode(id)
        ensureVisible(id)
    }
    // nearest other module in a direction (dx, dy are -1/0/1); the perpendicular offset counts double
    function neighbour(fromId, dx, dy) {
        var a = cardOf(fromId), best = "", bestScore = 1e18
        if (!a) return ""
        var ax = a.x + a.width / 2, ay = a.y + a.height / 2
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i].id === fromId) continue
            var c = nodeRepeater.itemAt(i)
            if (!c) continue
            var vx = c.x + c.width / 2 - ax, vy = c.y + c.height / 2 - ay
            var main = dx !== 0 ? vx * dx : vy * dy, side = dx !== 0 ? Math.abs(vy) : Math.abs(vx)
            if (main <= 1) continue
            var score = main + 2 * side
            if (score < bestScore) { bestScore = score; best = nodes[i].id }
        }
        return best
    }
    function nudge(dx, dy) {
        var c = cardOf(selectedNode)
        if (!c || !backend) return
        if (!moveBurst) { backend.beginMove(); moveBurst = true }
        burstTimer.restart()
        c.x = Math.max(0, c.x + dx)
        c.y = Math.max(0, c.y + dy)
        backend.moveNode(selectedNode, c.x, c.y)
        ensureVisible(selectedNode)
    }
    function cycleLinks(step) {
        if (connections.length === 0) { say("No links in this flow"); return }
        var cur = -1
        for (var i = 0; i < connections.length; i++) if (sameLink(connections[i], selectedLink)) cur = i
        selectedLink = connections[(cur + step + connections.length) % connections.length]
        var c = selectedLink
        var f = nodeById(c.from), t = nodeById(c.to)
        say("Link " + (f ? f.title : c.from) + " \u2192 " + (t ? t.title : c.to) + " selected - Delete removes it")
    }
    function showKbWire() {
        var k = kbWire, n = nodeById(k.from)
        if (!k.active || !n) { wireDrag = { active: false, from: "", index: 0, x: 0, y: 0 }; return }
        var q = k.target !== "" ? portPoint(k.target, k.inp, false) : portPoint(k.from, k.out, true)
        wireDrag = { active: true, from: k.from, index: k.out, x: q.x, y: q.y }
        var t = nodeById(k.target)
        var tin = t && t.inputs.length > k.inp ? t.inputs[k.inp].name : ""
        say("Linking " + n.title + "." + (n.outputs.length > k.out ? n.outputs[k.out].name : "") +
            (t ? " \u2192 " + t.title + "." + tin + "  (Enter connects, 1-9 input, Esc cancels)" : "  - arrows pick the target module, [ ] pick the output"))
    }
    function endKbWire() { kbWire = { active: false, from: "", out: 0, target: "", inp: 0 }; showKbWire() }
    function startKbWire() {
        var n = nodeById(selectedNode)
        if (!n) return
        if (n.outputs.length === 0) { say(n.title + " has no output to link from"); return }
        kbWire = { active: true, from: selectedNode, out: 0, target: "", inp: 0 }
        showKbWire()
    }
    function canvasKey(e) {
        var ctrl = (e.modifiers & Qt.ControlModifier) !== 0, shift = (e.modifiers & Qt.ShiftModifier) !== 0, alt = (e.modifiers & Qt.AltModifier) !== 0
        var dir = e.key === Qt.Key_Left ? [-1, 0] : e.key === Qt.Key_Right ? [1, 0] : e.key === Qt.Key_Up ? [0, -1] : e.key === Qt.Key_Down ? [0, 1] : null
        if (e.key === Qt.Key_Escape) {
            if (wireDrag.active && !kbWire.active) { cancelWire(); say("Link cancelled") }
            else if (kbWire.active) { endKbWire(); say("Link cancelled") }
            else if (selectedLink != null) selectedLink = null
            else return false
            return true
        }
        if (kbWire.active) {
            var k = kbWire
            if (dir) {
                var t = neighbour(k.target !== "" ? k.target : k.from, dir[0], dir[1])
                if (t !== "") { k.target = t; k.inp = 0; kbWire = k; selectedNode = t; ensureVisible(t); showKbWire() }
                return true
            }
            if (e.key === Qt.Key_BracketLeft || e.key === Qt.Key_BracketRight) {
                var fn = nodeById(k.from), cnt = fn ? fn.outputs.length : 1
                k.out = (k.out + (e.key === Qt.Key_BracketRight ? 1 : cnt - 1)) % cnt
                kbWire = k; showKbWire(); return true
            }
            if (e.key >= Qt.Key_1 && e.key <= Qt.Key_9) {
                var tn = nodeById(k.target)
                if (tn && e.key - Qt.Key_1 < tn.inputs.length) { k.inp = e.key - Qt.Key_1; kbWire = k; showKbWire() }
                return true
            }
            if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) {
                if (k.target === "") { say("Pick a target module with the arrow keys first"); return true }
                if (backend) backend.connectPorts(k.from, k.out, k.target, k.inp); else say("Connected (design-time preview)")
                endKbWire()
                return true
            }
            return false
        }
        if (dir && ctrl) { panX -= dir[0] * 60; panY -= dir[1] * 60; return true }
        if (dir && shift) { var st = alt ? 1 : 10; nudge(dir[0] * st, dir[1] * st); return true }
        if (dir) {
            if (selectedNode === "" && nodes.length) { selectModule(nodes[0].id); return true }
            var nb = neighbour(selectedNode, dir[0], dir[1])
            if (nb !== "") selectModule(nb)
            return true
        }
        switch (e.key) {
        case Qt.Key_Return: case Qt.Key_Enter:
            if (selectedNode !== "") { var n = nodeById(selectedNode); dialogs.showModule(selectedNode, n ? n.title : "") }
            return true
        case Qt.Key_F2: renameSelected(); return true
        case Qt.Key_K: cycleLinks(shift ? -1 : 1); return true
        case Qt.Key_L: startKbWire(); return true
        case Qt.Key_Plus: case Qt.Key_Equal: zoomAt(canvas.width / 2, canvas.height / 2, 1.2); return true
        case Qt.Key_Minus: zoomAt(canvas.width / 2, canvas.height / 2, 1 / 1.2); return true
        case Qt.Key_Home: fitView(); return true
        case Qt.Key_Backspace: deleteSelected(); return true
        }
        return false
    }

    function renameSelected() {
        var n = nodeById(selectedNode)
        if (n) dialogs.showRename(n.id, n.title, n.tool || "")
    }
    function cardAction(key) {
        if (key === "cfg") { var n = nodeById(selectedNode); dialogs.showModule(selectedNode, n ? n.title : "") }
        else if (key === "rename") renameSelected()
        else if (key === "run") { if (backend) backend.run() }
        else if (key === "del") deleteSelected()
        else if (key === "dellink") deleteSelected()
        else if (key === "ungroup") { if (backend) { var e1 = backend.setNodeGroup(selectedNode, ""); if (e1) say(e1) } }
        else if (key.indexOf("grp:") === 0) { if (backend) { var e2 = backend.setNodeGroup(selectedNode, key.substring(4)); if (e2) say(e2) } }
    }

    property bool inspectionVisible: false
    property bool aiVisible: false            // the floating AI Gen chat
    property int inspectionTab: 0
    property int railCategory: -1             // category whose tool flyout is open (-1 = closed)
    property string toast: ""                 // transient message shown in the status bar
    readonly property var imagePool: backend ? backend.imagePool : SampleData.imagePool
    readonly property int imageIndex: backend ? backend.imageIndex : 0
    readonly property var scopes: SampleData.scopes
    readonly property var categories: backend ? backend.toolCategories : SampleData.toolCategories

    function say(text) { toast = text; toastTimer.restart() }
    Timer { id: toastTimer; interval: 5000; onTriggered: root.toast = "" }

    // One entry point for every menu item and toolbar button.
    function invoke(key) {
        var b = backend
        if (key.indexOf("example") === 0) { if (b) b.newFromTemplate(parseInt(key.substring(7))); else say("Example solutions load in the running application"); return }
        if (key.indexOf("inspect") === 0 && key.length === 8) { inspectionTab = parseInt(key.substring(7)); inspectionVisible = true; return }
        switch (key) {
        case "startPage": if (b) b.showStartPage(); break
        case "newSolution": dialogs.show("newProject"); break
        case "openSolution": openDialog.open(); break
        case "save": if (b) b.saveProject(); else say("Saved (design-time preview)"); break
        case "saveAs": saveDialog.open(); break
        case "loadImage": imageDialog.open(); break
        case "loadFolder": folderDialog.open(); break
        case "exportCsv": csvDialog.open(); break
        case "exportXml": xmlExportDialog.open(); break
        case "importXml": xmlImportDialog.open(); break
        case "exit": if (b) b.requestClose(); else Qt.quit(); break
        case "globalVars": dialogs.show("globalVars"); break
        case "flowSettings": dialogs.show("flowSettings"); break
        case "hwTrigger": dialogs.showInfo("Hardware Trigger Settings",
            "Hardware / encoder triggering is not available in this build.\nFlows run from the software trigger (Once / Continuously)."); break
        case "comm": dialogs.show("comm"); break
        case "aiGen": aiVisible = !aiVisible; break
        case "lensCal": dialogs.show("lensCal"); break
        case "npoint": if (b) b.addTool("N-Point Calibration"); else say("N-Point Calibration module added"); break
        case "targetGen": dialogs.showInfo("Calibration Target Generator",
            "Pick a pattern (chessboard, circle grid, asymmetric circles), its size and a file name; a printable PNG target is written."); break
        case "plugins": dialogs.showPlugins(0); break
        case "pluginMarket": dialogs.showPlugins(1); break
        case "pluginGithub": dialogs.showPlugins(2); break
        case "pluginCreate": dialogs.showPlugins(3); break
        case "validate": dialogs.show("validation"); break
        case "arrange": if (b) b.arrange(); else say("Modules arranged"); break
        case "cameraSet": dialogs.show("cameraSet"); break
        case "controller": dialogs.showInfo("Controller Management",
            "This build has no separate controller layer.\nTo exchange results with a PLC or robot, add a TCP Send module to a flow."); break
        case "logViewer": dialogs.showInfo("Module Log", b ? b.moduleLog() : "01_ImageAcquisition   OK   2.1 ms"); break
        case "performance": dialogs.showInfo("Performance Options",
            "Cycle interval, stop-on-NG and the flow timeout are set per flow (Flow Settings).\nFlows run on a background worker, so the interface stays responsive."); break
        case "genDataset": datasetFolderDialog.open(); break
        case "gradcam": inspectionTab = 2; inspectionVisible = true; say("Open a failure in Failure Analysis to see its explanation"); break
        case "openExperiments": if (typeof appInspection !== "undefined") Qt.openUrlExternally(appInspection.storeDirectoryUrl()); else say("No experiment store yet"); break
        case "viewFlow": workspaceTab = 0; break
        case "viewOperation": workspaceTab = 1; break
        case "viewMulti": workspaceTab = 2; break
        case "fit": fitView(); break
        case "toggleGrid": showGrid = !showGrid; break
        case "manual": dialogs.showInfo("User Manual",
            "1. Open a module category in the tool rail and double-click a module to add it.\n2. Wire the Image output of the acquisition module into the next module.\n3. Double-click a module to set its parameters.\n4. Press Run, or turn on Loop to repeat until Stop.\n5. Read per-module verdicts in the Result panel."); break
        case "shortcuts": dialogs.showInfo("Keyboard Shortcuts",
            "Ctrl+N New   Ctrl+O Open   Ctrl+S Save   Ctrl+Shift+S Save As\nCtrl+Z Undo   Ctrl+Y Redo   Ctrl+1/2/3 Switch workspace tab\nDelete Remove selected   F1 User Manual\n\nFlow canvas (click it, or Tab to it):\nArrows select the neighbouring module   Shift+Arrows move it (Alt = 1 px)\nEnter configure   F2 rename   K / Shift+K select next / previous link   Delete remove\nL link from the selected module: [ ] output, arrows target, 1-9 input, Enter connect, Esc cancel\n+ / - zoom   Ctrl+Arrows pan   Home fit

Ctrl+G  AI Gen (describe a flow, get it built)

Linking with the mouse:
Drag from an output to an input (ports that fit light up and snap); drop on a module body to use its first free matching input.
Drag a connected input to move its wire; drop on empty canvas to remove it (Ctrl+Z restores).
Drag from a free input to link backwards to an output.   Esc cancels.   Click a wire to select it; its x button or Del removes it."); break
        case "language": dialogs.showInfo("Language", "Chinese localisation resources are not bundled with this build. The interface stays in English."); break
        case "version": dialogs.showInfo("Version Information",
            "Apex Industrial Vision Studio " + (backend ? backend.version : "") + "\nEngine: Python / PyQt6 / OpenCV / NumPy\nUser interface: Qt Quick (QML)"); break
        case "about": dialogs.showInfo("About Apex Industrial Vision Studio",
            "Apex Industrial Vision Studio " + (backend ? backend.version : "") + "\nA modular machine-vision platform and visual flow studio."); break
        default: say(key)
        }
    }

    // menu entries that mirror a setting show its live state
    function menuWithState(items) {
        var out = []
        for (var i = 0; i < items.length; i++) {
            var it = {}
            for (var k in items[i]) it[k] = items[i][k]
            if (it.key === "toggleGrid") it.checked = showGrid
            out.push(it)
        }
        return out
    }
    function nodeById(id) {
        for (var i = 0; i < nodes.length; i++) if (nodes[i].id === id) return nodes[i]
        return null
    }
    function portPoint(id, index, output) {
        var n = nodeById(id), p = pos[id]
        if (!n || !p) return Qt.point(0, 0)
        return Qt.point(p.x + (output ? 180.5 : -0.5), p.y + 26 + 4 + index * 14 + 4.5)
    }

    // ================================ MENU BAR =========================================
    Rectangle {
        id: menuBar
        anchors.top: parent.top
        width: parent.width
        height: Theme.heightMenuBar
        color: Theme.chrome

        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 14
            spacing: 2
            Repeater {
                model: SampleData.menus
                delegate: Rectangle {
                    id: menuLabel
                    width: menuText.implicitWidth + 20
                    height: 24
                    radius: 3
                    color: menuMouse.containsMouse ? Theme.chromeHover : "transparent"
                    Text {
                        id: menuText
                        anchors.centerIn: parent
                        text: modelData.title
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontBody
                        color: Theme.textPrimary
                    }
                    MouseArea {
                        id: menuMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            dropMenu.items = root.menuWithState(modelData.items)
                            dropMenu.x = menuLabel.mapToItem(menuBar, 0, 0).x
                            dropMenu.y = menuBar.height
                            dropMenu.open()
                        }
                    }
                }
            }
        }

        DropMenu {
            id: projMenu
            width: 240
            items: [ { text: "Start Page...", key: "startPage", shortcut: "Ctrl+H" }, { sep: true },
                     { text: "Open Solution...", key: "openSolution", shortcut: "Ctrl+O" },
                     { text: "Save Solution", key: "save", shortcut: "Ctrl+S" },
                     { text: "Save Solution As...", key: "saveAs", shortcut: "Ctrl+Shift+S" } ]
            onTriggered: function (key) { root.invoke(key) }
        }
        DropMenu {
            id: roleMenu
            width: 200
            items: [ { text: "Operator (run only)", key: "role:Operator", checked: root.role === "Operator" },
                     { text: "Engineer", key: "role:Engineer", checked: root.role === "Engineer" },
                     { text: "Administrator", key: "role:Administrator", checked: root.role === "Administrator" } ]
            onTriggered: function (key) { if (root.backend) root.backend.setRole(key.substring(5)) }
        }
        DropMenu {
            id: dropMenu
            onTriggered: function (key) { root.invoke(key) }
        }

        // corner: project chip | save | role chip
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Chip {
                width: 210
                icon: "folder"
                text: root.solutionName
                dirty: root.dirty
                onClicked: { projMenu.x = parent.mapToItem(menuBar, x, 0).x; projMenu.y = menuBar.height; projMenu.open() }
            }
            ChromeToolButton {
                width: 24; height: 24
                icon: "save"; tone: "dark"; tooltip: "Save solution (Ctrl+S)"
                opacity: root.dirty ? 1 : 0.45
                onClicked: if (root.backend) root.backend.saveProject()
            }
            Rectangle { width: 1; height: 16; color: Theme.chromeOutline; anchors.verticalCenter: parent.verticalCenter }
            Chip {
                id: roleChip
                width: 130
                icon: "user"
                text: root.role
                onClicked: { roleMenu.x = parent.mapToItem(menuBar, x, 0).x; roleMenu.y = menuBar.height; roleMenu.open() }
            }
        }
    }

    // ================================ TOOLBAR 1 ========================================
    Rectangle {
        id: toolbar1
        anchors.top: menuBar.bottom
        width: parent.width
        height: Theme.heightToolbar
        color: Theme.chromeDark

        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 12
            spacing: 6
            Rectangle {      // brand mark
                width: 30; height: 30; color: "transparent"
                Image { anchors.centerIn: parent; width: 26; height: 26; source: "../images/app_icon.svg"; sourceSize: Qt.size(52, 52); smooth: true }
            }
            ChromeToolButton { icon: "save"; tooltip: "Save solution (Ctrl+S)"; onClicked: root.invoke("save") }
            ChromeToolButton { icon: "open"; tooltip: "Open solution (Ctrl+O)"; onClicked: root.invoke("openSolution") }
            ChromeToolButton { icon: "image"; tooltip: "Load image files (Ctrl+I)"; onClicked: root.invoke("loadImage") }
            ChromeToolButton { icon: "undo"; tooltip: "Undo (Ctrl+Z)"; onClicked: if (root.backend) root.backend.undo(); else root.say("Undo") }
            ChromeToolButton { icon: "redo"; tooltip: "Redo (Ctrl+Y)"; onClicked: if (root.backend) root.backend.redo(); else root.say("Redo") }
            Rectangle { width: 1; height: 24; color: Theme.chromeDivider; anchors.verticalCenter: parent.verticalCenter }
            ChromeToolButton { icon: "lock"; tooltip: root.role === "Operator" ? "Editing locked - click to unlock (Engineer)" : "Lock editing (Operator)"; checked: root.role === "Operator"; onClicked: if (root.backend) root.backend.setRole(root.role === "Operator" ? "Engineer" : "Operator") }
            ChromeToolButton { icon: "camera"; tooltip: "Camera set"; onClicked: root.invoke("cameraSet") }
            ChromeToolButton { icon: "table"; tooltip: "Controller management"; onClicked: root.invoke("controller") }
            ChromeToolButton { icon: "variable"; tooltip: "Global variables"; onClicked: root.invoke("globalVars") }
            ChromeToolButton { icon: "bolt"; tooltip: "Hardware trigger settings"; onClicked: root.invoke("hwTrigger") }
            ChromeToolButton { icon: "script"; tooltip: "Communication configuration"; onClicked: root.invoke("comm") }
            Rectangle { width: 1; height: 24; color: Theme.chromeDivider; anchors.verticalCenter: parent.verticalCenter }
            // `color` is not a ChromeToolButton property - these two carried a dead literal
            // that had no effect, because the fill comes from `kind`.  Removed so the run and
            // stop hues are set in exactly one place (the component's tokens).
            // the top buttons act on ALL flows; the run / loop beside the flow tabs and the ones under the image act on the open flow
            ChromeToolButton { objectName: "runAllFlows"; icon: "run"; kind: "run"; tooltip: "Run all flows"; width: 40; onClicked: if (root.backend) root.backend.runAll() }
            ChromeToolButton { objectName: "loopAllFlows"; icon: "loop"; tooltip: "Loop all flows until Stop"; checked: root.allLoopOn; onClicked: root.setAllLoop(!root.allLoopOn) }
            ChromeToolButton { objectName: "stopAllFlows"; icon: "stop"; kind: "stop"; tooltip: "Stop all flows"; width: 40; onClicked: if (root.backend) root.backend.stopAll() }
            StatusBadge {
                anchors.verticalCenter: parent.verticalCenter
                text: root.running ? "RUNNING" : root.verdict
                kind: root.running ? "run" : root.verdict === "PASS" ? "ok" : "error"
            }
        }
    }

    ChromePillButton {
        id: aiButton
        objectName: "aiGenButton"
        anchors.right: parent.right
        anchors.rightMargin: 12
        y: toolbar1.y + (toolbar1.height - height) / 2
        z: 5
        icon: "sparkle"
        text: "AI Gen"
        tooltip: "Describe a flow in words and let AI build it (Ctrl+G)"
        checked: root.aiVisible
        onClicked: root.invoke("aiGen")
    }

    // ================================ TOOLBAR 2 ========================================
    Rectangle {
        id: toolbar2
        anchors.top: toolbar1.bottom
        width: parent.width
        height: Theme.heightTabBar
        color: Theme.chromeDark

        // the flow controls stay where they are; only the tabs beside them scroll
        Row {
            id: flowControls
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 6
            spacing: 6
            // these two (and the Run / Loop under the image) act on the open flow only - the same state, shown the same way
            ChromeToolButton { objectName: "runThisFlow"; icon: root.running ? "stop" : "run"; kind: ""; tooltip: root.running ? "Stop this flow" : "Run this flow"; width: 30; height: 28; tone: "light"
                               onClicked: if (root.backend) (root.running ? root.backend.stop() : root.backend.run()) }
            ChromeToolButton { objectName: "loopThisFlow"; icon: "loop"; tooltip: "Loop this flow until Stop"; width: 30; height: 28; checked: root.loopOn; onClicked: root.setLoop(!root.loopOn) }
            ChromeToolButton { icon: "plus"; tooltip: "Add a sub-flow"; width: 30; height: 28; onClicked: if (root.backend) root.backend.addFlow(); else root.say("Flow added") }
            ChromeToolButton { icon: "check"; tooltip: "Validate flow"; width: 30; height: 28; onClicked: root.invoke("validate") }
        }
        Rectangle { id: flowSep; x: flowControls.x + flowControls.width + 8; width: 1; height: 22; color: Theme.chromeOutline; anchors.verticalCenter: parent.verticalCenter }
        Flickable {       // one tab per flow of the solution; scrolls sideways (wheel, drag) when there are many
            id: flowTabs
            objectName: "flowTabs"
            anchors.verticalCenter: parent.verticalCenter
            x: flowSep.x + 9
            height: 28
            width: Math.max(60, flowRight.x - 10 - x)
            contentWidth: tabsRow.width; contentHeight: 28
            clip: true; interactive: contentWidth > width
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            
            // the wheel moves the tabs sideways
            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: function (e) {
                    var d = e.angleDelta.x !== 0 ? e.angleDelta.x : e.angleDelta.y
                    flowTabs.contentX = Math.max(0, Math.min(flowTabs.contentWidth - flowTabs.width, flowTabs.contentX - d))
                }
            }
            // bring the chosen (or newly added) tab into view - but only when the choice changes, so a manual scroll is left alone
            function showActive() {
                var edge = 0
                for (var i = 0; i < tabsRow.children.length; i++) {
                    var tab = tabsRow.children[i]
                    if (!tab || tab.width === undefined) continue
                    var l = edge, r = edge + tab.width
                    edge = r + tabsRow.spacing
                    if (i >= root.tabList.length) break
                    if (!root.tabList[i].active) continue
                    if (l < contentX) contentX = l
                    else if (r > contentX + width) contentX = r - width
                }
            }
            Connections { target: root; function onTabKeyChanged() { Qt.callLater(flowTabs.showActive) } }
            onWidthChanged: Qt.callLater(showActive)
            Row {
                id: tabsRow
                spacing: 2
                Repeater {
                    model: root.tabList
                    delegate: Rectangle {
                        objectName: "flowTab_" + modelData.name
                        // The width follows the label.  It was a fixed 190 px, but the
                        // label needs 171 px of *text* once the 10 px left inset and the
                        // close button are taken out, so the cycle time was elided to
                        // "FAIL 1…".  Content width with a floor keeps short names tidy and
                        // lets a long one show its verdict and timing; past 320 px Qt's own
                        // elision takes over, which is the correct fallback.
                        width: Math.max(190, Math.min(320, tabLabel.implicitWidth + 44))
                        height: 28
                        color: modelData.active ? "#8a5a0e" : (tabHover.containsMouse ? Theme.railHover : "transparent")      // dark amber: white text stays readable
                        border.width: 1; border.color: modelData.active ? Theme.accent : Theme.chromeOutline
                        MouseArea { id: tabHover; anchors.fill: parent; hoverEnabled: true
                                    onClicked: if (root.backend) root.backend.selectFlow(modelData.name) }
                        Text {
                            id: tabLabel
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left; anchors.leftMargin: 10
                            anchors.right: closeIcon.left; anchors.rightMargin: 4
                            elide: Text.ElideRight
                            text: (modelData.running ? "\u25B6 " : (modelData.active ? "\u25CF " : "")) + modelData.name
                                  + (modelData.verdict !== "" ? "  " + modelData.verdict + "  " + modelData.ms + "ms" : "")
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption
                            font.bold: modelData.active
                            color: "#ffffff"
                        }
                        Icon {
                            id: closeIcon
                            objectName: "flowClose_" + modelData.name
                            name: "close"; tone: "light"; size: 14
                            visible: root.tabList.length > 1
                            anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
                            MouseArea { anchors.fill: parent; anchors.margins: -4
                                        onClicked: if (root.backend) root.backend.closeFlow(modelData.name) }
                        }
                    }
                }
            }
        }
        Row {
            id: flowRight
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 14
            ChromeToolButton { icon: "layers"; tooltip: "Operation interface (Ctrl+2)"; width: 28; height: 28; onClicked: root.invoke("viewOperation") }
            ChromeToolButton { icon: "histogram"; tooltip: "Evaluation results"; width: 28; height: 28; onClicked: root.invoke("inspect1") }
            ChromeToolButton { icon: "fit"; tooltip: "Fit modules to view (Ctrl+0)"; width: 28; height: 28; onClicked: root.invoke("fit") }
            ChromeToolButton { icon: "roi"; tooltip: "Flow diagram (Ctrl+1)"; width: 28; height: 28; onClicked: root.invoke("viewFlow") }
            ChromeToolButton { icon: "script"; tooltip: "Flow settings"; width: 28; height: 28; onClicked: root.invoke("flowSettings") }
            ChromeToolButton { icon: "comm"; tooltip: "Multi-flow overview (Ctrl+3)"; width: 28; height: 28; onClicked: root.invoke("viewMulti") }
        }
    }

    // ================================ BODY =============================================
    Item {
        id: body
        anchors.top: toolbar2.bottom
        anchors.bottom: statusBar.top
        width: parent.width

        // ---- tool rail ----------------------------------------------------------------
        Rectangle {
            id: rail
            width: Theme.railWidth
            height: parent.height
            color: Theme.rail
            property int current: root.railCategory
            Column {
                anchors.top: parent.top
                anchors.topMargin: 4
                width: parent.width
                Repeater {
                    model: root.categories
                    delegate: Rectangle {
                        width: rail.width; height: 40
                        color: rail.current === index ? Theme.panelAlt : (railMouse.containsMouse ? Theme.railHover : "transparent")
                        Rectangle { visible: rail.current === index; width: 3; height: parent.height; color: Theme.accent }
                        Icon { anchors.centerIn: parent; name: modelData.icon; tone: rail.current === index ? "dark" : "light"; size: 20 }
                        MouseArea {
                            id: railMouse; anchors.fill: parent; hoverEnabled: true
                            onClicked: root.railCategory = (root.railCategory === index ? -1 : index)
                        }
                    }
                }
            }
            Icon { name: "search"; tone: "light"; size: 20; anchors.bottom: parent.bottom; anchors.bottomMargin: 12; anchors.horizontalCenter: parent.horizontalCenter }
            MouseArea { width: parent.width; height: 40; anchors.bottom: parent.bottom; onClicked: root.railCategory = (root.railCategory < 0 ? 0 : -1) }
        }

        // ---- workspace (left) ---------------------------------------------------------
        Item {
            id: workspace
            anchors.left: rail.right
            anchors.right: rightColumn.left
            height: parent.height

            Row {
                id: wsTabs
                Repeater {
                    model: ["Flow Diagram", "Operation Interface", "Multi-Flow"]
                    delegate: TabButton2 {
                        text: modelData
                        selected: root.workspaceTab === index
                        onClicked: root.workspaceTab = index
                    }
                }
            }

            // ---- flow canvas ----------------------------------------------------------
            Rectangle {
                id: canvas
                objectName: "flowCanvas"
                anchors.top: wsTabs.bottom
                anchors.bottom: parent.bottom
                width: parent.width
                color: Theme.canvas
                clip: true
                visible: root.workspaceTab === 0

                // dotted grid
                Canvas {
                    visible: root.showGrid
                    anchors.fill: parent
                    anchors.leftMargin: -37
                    anchors.rightMargin: 37
                    anchors.topMargin: -8
                    anchors.bottomMargin: 8
                    onPaint: {
                        var c = getContext("2d")
                        c.fillStyle = "" + Theme.canvasDot
                        for (var x = 8; x < width; x += 16)
                            for (var y = 8; y < height; y += 16) c.fillRect(x, y, 1.5, 1.5)
                    }
                }

                // pinch to zoom (touch screen, or a touchpad gesture on platforms that deliver one); two fingers also pan.
                // A precision touchpad on Windows reports its pinch as Ctrl + wheel, which the wheel zoom below handles.
                PinchHandler {
                    id: canvasPinch
                    objectName: "canvasPinch"
                    target: null                                   // the view is moved by root.zoom / root.panX, not by this handler
                    acceptedDevices: PointerDevice.TouchScreen | PointerDevice.TouchPad
                    minimumScale: 0.001
                    maximumScale: 1000
                    property real lastScale: 1.0
                    property real lastX: 0
                    property real lastY: 0
                    onActiveChanged: { lastScale = 1.0; lastX = centroid.position.x; lastY = centroid.position.y }
                    onActiveScaleChanged: if (active && lastScale > 0) { root.zoomAt(centroid.position.x, centroid.position.y, activeScale / lastScale); lastScale = activeScale }
                    onCentroidChanged: if (active) {
                        root.panX += centroid.position.x - lastX; root.panY += centroid.position.y - lastY
                        lastX = centroid.position.x; lastY = centroid.position.y
                    }
                }

                // empty canvas: drag to pan, wheel to zoom
                MouseArea {
                    id: panArea
                    anchors.fill: parent
                    property real lastX: 0
                    property real lastY: 0
                    acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                    hoverEnabled: true
                    cursorShape: root.hoverLink != null ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onExited: root.hoverLink = null
                    onPressed: function (m) {
                        lastX = m.x; lastY = m.y; canvas.forceActiveFocus(); root.railCategory = -1
                        var hit = root.linkAt((m.x - root.panX) / root.zoom, (m.y - root.panY) / root.zoom)
                        root.selectedLink = hit
                        if (hit != null && m.button === Qt.RightButton) { linkMenu.x = m.x; linkMenu.y = m.y; linkMenu.open() }
                    }
                    onPositionChanged: function (m) {
                        if (!pressed) { root.hoverLink = root.wireDrag.active ? null : root.linkAt((m.x - root.panX) / root.zoom, (m.y - root.panY) / root.zoom); return }
                        if (pressedButtons & Qt.RightButton) return
                        root.panX += m.x - lastX; root.panY += m.y - lastY; lastX = m.x; lastY = m.y
                    }
                    onWheel: function (w) { root.zoomAt(w.x, w.y, root.wheelFactor(w)) }
                }

                Item {
                    id: scene
                    width: 4000
                    height: 4000
                    transformOrigin: Item.TopLeft
                    scale: root.zoom
                    x: root.panX
                    y: root.panY

                    // wires first, so cards sit on top
                    Repeater {
                        model: root.connections
                        delegate: Shape {
                            id: wire
                            anchors.fill: parent
                            visible: !root.sameLink(modelData, root.hiddenLink)
                            readonly property bool sel: root.sameLink(modelData, root.selectedLink)
                            readonly property bool hov: root.sameLink(modelData, root.hoverLink)
                            property point a: root.portPoint(modelData.from, modelData.fromPort, true)
                            property point b: root.portPoint(modelData.to, modelData.toPort, false)
                            property real dx: root.wireDx(a, b)
                            ShapePath {
                                strokeColor: wire.sel ? Theme.accent : root.wireColor(modelData)
                                strokeWidth: wire.sel ? 4.5 : (wire.hov ? 3.5 : 2.5)
                                fillColor: "transparent"
                                capStyle: ShapePath.RoundCap
                                startX: wire.a.x; startY: wire.a.y
                                PathCubic { control1X: wire.a.x + wire.dx; control1Y: wire.a.y; control2X: wire.b.x - wire.dx; control2Y: wire.b.y; x: wire.b.x; y: wire.b.y }
                            }
                        }
                    }

                    // the wire being dragged: leaves the port it was picked up from, snaps to a port that fits
                    Shape {
                        id: tempWire
                        objectName: "tempWire"
                        anchors.fill: parent
                        visible: root.wireDrag.active
                        readonly property bool rev: !!root.wireDrag.reverse
                        readonly property var tgt: root.wireDrag.target
                        readonly property point anchorPt: root.wireDrag.active ? root.portPoint(root.wireDrag.from, root.wireDrag.index, !rev) : Qt.point(0, 0)
                        readonly property point freePt: tgt ? Qt.point(tgt.x, tgt.y) : Qt.point(root.wireDrag.x, root.wireDrag.y)
                        property point a: rev ? freePt : anchorPt          // always drawn output -> input
                        property point b: rev ? anchorPt : freePt
                        property real dx: root.wireDx(a, b)
                        ShapePath {
                            strokeColor: tempWire.tgt && !tempWire.tgt.ok ? Theme.errorBorder
                                         : Theme.portColor(root.wireDrag.active ? root.portDtype(root.wireDrag.from, root.wireDrag.index, !tempWire.rev) : "", "value")
                            strokeWidth: 3
                            strokeStyle: tempWire.tgt ? ShapePath.SolidLine : ShapePath.DashLine
                            dashPattern: [4, 3]
                            fillColor: "transparent"
                            capStyle: ShapePath.RoundCap
                            startX: tempWire.a.x; startY: tempWire.a.y
                            PathCubic { control1X: tempWire.a.x + tempWire.dx; control1Y: tempWire.a.y; control2X: tempWire.b.x - tempWire.dx; control2Y: tempWire.b.y
                                        x: tempWire.b.x; y: tempWire.b.y }
                        }
                    }

                    Repeater {
                        id: groupFrameRepeater
                        model: root.groupFrameList
                        delegate: Rectangle {
                            objectName: "groupFrame"
                            x: modelData.x; y: modelData.y; width: modelData.w; height: modelData.h
                            radius: 10
                            color: Qt.rgba(Theme.primary.r, Theme.primary.g, Theme.primary.b, 0.06)
                            border.width: 1; border.color: Qt.rgba(Theme.primary.r, Theme.primary.g, Theme.primary.b, 0.55)
                            Text {
                                x: 10; y: 3
                                text: modelData.title + "  (" + modelData.count + " module" + (modelData.count === 1 ? "" : "s") + ")"
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; font.weight: Font.DemiBold; color: Theme.primary
                            }
                        }
                    }

                    Repeater {
                        id: nodeRepeater
                        model: root.nodeIds
                        delegate: NodeCard {
                            readonly property var d: root.cardData(modelData)      // modelData is the module's id
                            x: d.x
                            y: d.y
                            onDChanged: if (!dragging) { x = d.x; y = d.y }          // a drag breaks the x/y bindings; keep following the model otherwise
                            title: d.title
                            toolName: d.tool || ""
                            status: d.status
                            ms: d.ms
                            inputs: d.inputs
                            outputs: d.outputs
                            selected: root.selectedNode === modelData
                            onClicked: { root.selectedLink = null; root.selectedNode = modelData; canvas.forceActiveFocus(); if (root.backend) root.backend.selectNode(modelData) }
                            onDoubleClicked: dialogs.showModule(modelData, d.title)
                            function publish() {
                                // a NEW object each time: mutating it in place is not seen as a change,
                                // so the wires (bound to `pos`) would never follow a dragged module
                                var p = {}
                                for (var k in root.pos) p[k] = root.pos[k]
                                p[modelData] = { x: x, y: y }
                                root.pos = p
                            }
                            onXChanged: publish()
                            onYChanged: publish()
                            Component.onCompleted: publish()
                            onDragStarted: if (root.backend) root.backend.beginMove()
                            onMoved: if (root.backend) root.backend.moveNode(modelData, x, y)
                            inputState: (root.portStates[modelData] || { inputs: [] }).inputs
                            outputState: (root.portStates[modelData] || { outputs: [] }).outputs
                            inputLinked: root.linkedInputs(modelData)
                            onWireStarted: function (index) { root.selectedNode = modelData; root.beginWire(modelData, index, true, null) }
                            onWireMoved: function (p) { root.moveWire(p) }
                            onWireDropped: function (p) { root.endWire(p) }
                            onInputWireStarted: function (index) {
                                var held = null
                                for (var i = 0; i < root.connections.length; i++)
                                    if (root.connections[i].to === modelData && root.connections[i].toPort === index) held = root.connections[i]
                                if (held) root.beginWire(held.from, held.fromPort, true, held)       // pick the wire up by its end
                                else root.beginWire(modelData, index, false, null)                // free input: link backwards
                            }
                            onInputWireMoved: function (p) { root.moveWire(p) }
                            onInputWireDropped: function (p) { root.endWire(p) }
                            onInputCleared: function (index) {
                                if (root.backend) root.backend.disconnectInput(modelData, index); else root.say("Input disconnected")
                            }
                            onContextRequested: function (p) {
                                root.selectedNode = modelData
                                var c = scene.mapToItem(canvas, p.x, p.y)
                                cardMenu.x = c.x; cardMenu.y = c.y
                                var base = [ { text: "Module Configuration...", key: "cfg", shortcut: "Enter" }, { text: "Rename...", key: "rename", shortcut: "F2" },
                                             { text: "Execute Module", key: "run" } ]
                                var groups = root.backend ? root.backend.groupsFor(modelData) : []
                                if (groups.length) base.push({ sep: true })
                                for (var gi = 0; gi < groups.length; gi++)
                                    base.push({ text: (groups[gi].current ? "In group: " : "Add to group: ") + groups[gi].title, key: groups[gi].current ? "ungroup" : "grp:" + groups[gi].id })
                                if (d.group) base.push({ text: "Take out of group", key: "ungroup" })
                                base.push({ sep: true }); base.push({ text: "Delete Module", key: "del", shortcut: "Del" })
                                cardMenu.items = base
                                cardMenu.open()
                            }
                        }
                    }
                }

                // halos on the ports that can take the dragged wire; the snapped one is solid
                Repeater {
                    model: root.wireRings
                    delegate: Rectangle {
                        z: 60
                        x: root.panX + modelData.x * root.zoom - 10; y: root.panY + modelData.y * root.zoom - 10      // canvas coordinates
                        width: 20; height: 20; radius: 10
                        color: modelData.state === "hot" ? "#3322c55e" : (modelData.state === "bad" ? "#33dc2626" : "transparent")
                        border.width: modelData.state === "cand" ? 1 : 2
                        border.color: modelData.state === "hot" ? Theme.portHot : (modelData.state === "bad" ? Theme.errorBorder : Theme.portColor(root.portDtype(root.wireDrag.from, root.wireDrag.index, !root.wireDrag.reverse), "value"))
                        opacity: modelData.state === "cand" ? 0.6 : 1
                    }
                }

                // delete handle on the selected link
                Rectangle {
                    id: linkHandle
                    objectName: "linkDelete"
                    z: 60
                    readonly property var l: root.selectedLink
                    readonly property point pa: l ? root.portPoint(l.from, l.fromPort, true) : Qt.point(0, 0)
                    readonly property point pb: l ? root.portPoint(l.to, l.toPort, false) : Qt.point(0, 0)
                    visible: l != null && !root.wireDrag.active
                    x: root.panX + (pa.x + pb.x) / 2 * root.zoom - 11; y: root.panY + (pa.y + pb.y) / 2 * root.zoom - 11
                    width: 22; height: 22; radius: 11
                    color: lhMouse.containsMouse ? Theme.errorBorder : Theme.errorBg
                    border.width: 1; border.color: Theme.errorBorder
                    Icon { anchors.centerIn: parent; name: "close"; size: 12; tone: lhMouse.containsMouse ? "white" : "dark" }
                    MouseArea { id: lhMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.deleteSelected() }
                    ToolTip.visible: lhMouse.containsMouse; ToolTip.delay: 400; ToolTip.text: "Delete this link (Del)"
                }

                DropMenu {
                    id: cardMenu
                    width: 230
                    items: [ { text: "Module Configuration...", key: "cfg", shortcut: "Enter" }, { text: "Rename...", key: "rename", shortcut: "F2" },
                             { text: "Execute Module", key: "run" },
                             { sep: true }, { text: "Delete Module", key: "del", shortcut: "Del" } ]
                    onTriggered: function (key) { root.cardAction(key) }
                }

                DropMenu {
                    id: linkMenu
                    width: 200
                    items: [ { text: "Delete Link", key: "dellink", shortcut: "Del" } ]
                    onTriggered: function (key) { root.cardAction(key) }
                }

                focus: true
                Keys.onDeletePressed: root.deleteSelected()
                Keys.onPressed: function (e) { e.accepted = root.canvasKey(e) }
                activeFocusOnTab: true
                border.width: activeFocus ? 2 : 0
                border.color: Theme.primary
                Accessible.role: Accessible.Pane
                Accessible.name: "Flow canvas. Arrow keys select modules, Shift plus arrows move, L links, K selects links, Delete removes."

                // zoom tool + telemetry chips (lower-left, as in the widget UI)
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 8
                    spacing: 8
                    Rectangle {
                        width: 118; height: 24
                        radius: Theme.radiusPanel
                        color: Theme.panelAlt
                        border.width: 1; border.color: Theme.fieldBorder
                        Row {
                            anchors.centerIn: parent
                            spacing: 4
                            Text { width: 34; horizontalAlignment: Text.AlignHCenter; text: Math.round(root.zoom * 100) + "%"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; font.weight: Font.DemiBold; color: Theme.textPrimary; anchors.verticalCenter: parent.verticalCenter }
                            Repeater {
                                model: [ { t: "\u2212", tip: "Zoom out" }, { t: "+", tip: "Zoom in" }, { t: "\u25A1", tip: "Fit the flow to the canvas" } ]
                                delegate: Rectangle {
                                    width: 26; height: 24; radius: 3
                                    anchors.verticalCenter: parent.verticalCenter
                                    ToolTip.visible: zoomMouse.containsMouse
                                    ToolTip.delay: 500
                                    ToolTip.text: modelData.tip
                                    color: zoomMouse.containsMouse ? Theme.buttonHover : "transparent"
                                    Text { anchors.centerIn: parent; text: modelData.t; font.pixelSize: index === 2 ? 12 : 14; color: Theme.textPrimary }
                                    MouseArea {
                                        id: zoomMouse; anchors.fill: parent; hoverEnabled: true
                                        onClicked: index === 0 ? root.zoomAt(canvas.width / 2, canvas.height / 2, 1 / 1.2)
                                                 : index === 1 ? root.zoomAt(canvas.width / 2, canvas.height / 2, 1.2) : root.fitView()
                                    }
                                }
                            }
                        }
                    }
                    TelemetryChip { color: "#00f8fafb"; text: "Flow: " + root.flowMs.toFixed(2) + "ms"; border.color: "#006f4a04"; emphasis: true; anchors.verticalCenter: parent.verticalCenter ;clip: false }
                    TelemetryChip { color: "#00f8fafb"; text: "Tools: " + root.toolCount; border.color: "#00aab3b9"; anchors.verticalCenter: parent.verticalCenter }
                    TelemetryChip { color: "#00f8fafb"; text: "Algo: " + root.algoMs.toFixed(2) + "ms"; anchors.verticalCenter: parent.verticalCenter }
                }
            }

            // ---- operation interface (layer switches) ---------------------------------
            Rectangle {
                anchors.top: wsTabs.bottom
                anchors.bottom: parent.bottom
                width: parent.width
                color: Theme.panelAlt
                visible: root.workspaceTab === 1
                Column {
                    x: 16; y: 14
                    spacing: 10
                    Text { text: "Display & Formatting"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontLabel; font.weight: Font.DemiBold; color: Theme.textPrimary }
                    Text { text: "Control which result overlays are rendered over the inspection image."; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Repeater {
                        model: [ { t: "All Overlays", k: "overlays" }, { t: "ROIs & Defect Boxes", k: "rois" }, { t: "Measurements & Labels", k: "metrics" },
                                 { t: "Datum & Crosshairs", k: "datums" }, { t: "Coordinate Reticle Crosshair", k: "crosshair" },
                                 { t: "Intensity Histogram HUD", k: "histogram" }, { t: "Flow Canvas Alignment Grid", k: "grid" } ]
                        delegate: Row {
                            spacing: 10
                            ToggleSwitch {
                                checked: modelData.k === "grid" ? root.showGrid : root.layers[modelData.k] === true
                                onToggled: function (value) {
                                    if (modelData.k === "grid") root.showGrid = value
                                    else if (root.backend) root.backend.setLayer(modelData.k, value)
                                }
                            }
                            Text { text: modelData.t; anchors.verticalCenter: parent.verticalCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                        }
                    }
                    Text { text: "Output Parameter Formatting"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontLabel; font.weight: Font.DemiBold; color: Theme.textPrimary }
                    Rectangle {
                        width: 640; height: 150; radius: Theme.radiusPanel; color: "#f3f5f6"; border.width: 1; border.color: Theme.fieldBorder; clip: true
                        Text { x: 10; y: 8; width: parent.width - 20; wrapMode: Text.WrapAnywhere
                            text: root.formatted !== "" ? root.formatted : "Run the flow to preview the formatted output string."
                            font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textPrimary }
                    }
                }
            }

            // ---- multi-flow overview --------------------------------------------------
            Rectangle {
                anchors.top: wsTabs.bottom
                anchors.bottom: parent.bottom
                width: parent.width
                color: Theme.canvas
                visible: root.workspaceTab === 2

                // One card per flow, laid out in a wrapping grid.  This previously drew a
                // single card centred on the canvas with the flow name "PCB_AOI_Solution"
                // and the timing taken from the *active* flow, so on any other project the
                // overview named a flow that did not exist and showed another flow's
                // numbers.  It now reads the same `tabList` the tab bar uses, so the two
                // cannot disagree.
                // A Grid sizes itself to its children, so anchoring it centred puts the
                // block in the middle whatever the flow count.  `Flow` looked right but
                // reports no implicit size, so `centerIn` collapsed it to a corner; that is
                // why the old single card sat off-centre.
                Grid {
                    anchors.centerIn: parent
                    columns: Math.max(1, Math.min(root.tabList.length,
                                                  Math.floor((parent.width - 40) / 206)))
                    spacing: 20
                    Repeater {
                        model: root.tabList
                        delegate: Rectangle {
                            width: 186; height: 100
                            radius: 6; color: Theme.card
                            border.width: 2
                            border.color: modelData.verdict === "FAIL" ? Theme.errorBorder
                                        : modelData.verdict === "PASS" ? Theme.okBorder
                                        : Theme.fieldBorder
                            Text {
                                x: 10; y: 8; width: parent.width - 20
                                text: modelData.name
                                elide: Text.ElideRight
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody
                                font.weight: Font.DemiBold; color: Theme.textPrimary
                            }
                            Row {
                                x: 10; y: 34; spacing: 8
                                AppButton { text: ""; icon: "run"; kind: "secondary"; width: 36
                                            onClicked: if (root.backend) root.backend.selectFlow(modelData.name) }
                                AppButton { text: ""; icon: "loop"; kind: "secondary"; width: 36 }
                            }
                            Text { x: 10; y: 74
                                   text: modelData.ms !== undefined ? modelData.ms + "ms" : "-"
                                   font.family: Theme.monoFamily;
                                   font.pixelSize: Theme.fontCaption; color: Theme.textPrimary }
                            Text { anchors.right: parent.right; anchors.rightMargin: 10; y: 74
                                   text: modelData.verdict !== "" ? modelData.verdict : "NOT RUN"
                                   font.pixelSize: Theme.fontCaption; font.weight: Font.Bold
                                   color: modelData.verdict === "PASS" ? Theme.okText
                                        : modelData.verdict === "FAIL" ? Theme.errorText
                                        : Theme.textMuted }
                        }
                    }
                }
            }
        }

        // ---- right column: image viewer, strip, results ---------------------------------
        Rectangle {
            id: rightColumn
            anchors.right: parent.right
            // The canvas and this column hold a 6:4 split of the space beside the rail, at
            // any window size.  A fixed 640 px made the ratio drift with the window: at 1600
            // it was 59:41, but at 1280 the image column was wider than the canvas, and on a
            // wide monitor the canvas ate the column.
            width: Math.round(Math.max(360,
                        Math.min((parent.width - rail.width) * 0.4,
                                 parent.width - rail.width - 320)))
            height: parent.height
            color: Theme.panel

            Row {
                id: rcTabs
                TabButton2 { objectName: "tabImage";  text: "Image";  selected: root.viewTab === "image";  onClicked: root.viewTab = "image" }
                TabButton2 { objectName: "tabResult"; text: "Result"; selected: root.viewTab === "result"; onClicked: root.viewTab = "result" }
            }
            Rectangle {      // the Result tab: every module's result in one table, in place of the image viewer
                id: resultPage
                objectName: "resultPage"
                visible: root.viewTab === "result"
                anchors.top: rcTabs.bottom
                width: parent.width
                height: 350                   // the room the image header, viewer and read-out use
                color: Theme.panelAlt
                Rectangle {
                    id: rpHead
                    width: parent.width; height: 28
                    color: Theme.panelHeader
                    Text { x: 8; anchors.verticalCenter: parent.verticalCenter
                           text: "Module Results  ·  " + root.verdict + "  ·  " + root.flowMs.toFixed(1) + " ms"
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary }
                }
                Rectangle {
                    id: rpCols
                    anchors.top: rpHead.bottom
                    width: parent.width; height: 24
                    color: "#e6eaec"
                    Text { x: 10;  anchors.verticalCenter: parent.verticalCenter; text: "Module"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 196; anchors.verticalCenter: parent.verticalCenter; text: "Status"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 262; anchors.verticalCenter: parent.verticalCenter; text: "Time";   font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 330; anchors.verticalCenter: parent.verticalCenter; text: "Result"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                }
                ListView {
                    id: rpList
                    objectName: "resultList"
                    anchors.top: rpCols.bottom
                    anchors.bottom: parent.bottom
                    width: parent.width
                    clip: true
                    model: root.moduleRows
                    delegate: Rectangle {
                        width: ListView.view.width; height: 36
                        color: root.selectedNode === modelData.id ? Theme.accentDim : (index % 2 ? "#f1f4f5" : Theme.panelAlt)
                        Text { x: 10; width: 178; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
                               text: modelData.name; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary }
                        Text { x: 196; width: 60; anchors.verticalCenter: parent.verticalCenter
                               text: modelData.status; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.Bold
                               color: modelData.bad ? Theme.errorText : modelData.status === "OK" ? Theme.okText : Theme.textMuted }
                        Text { x: 262; width: 60; anchors.verticalCenter: parent.verticalCenter
                               text: modelData.status === "-" ? "" : modelData.ms.toFixed(1) + " ms"; font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
                        Text { x: 330; width: 300; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight
                               text: modelData.summary !== "" ? modelData.summary : modelData.message
                               font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textPrimary }
                        MouseArea { anchors.fill: parent; onClicked: root.selectModule(modelData.id) }
                    }
                }
            }
            Rectangle {      // image header
                id: imgHeader
                visible: root.viewTab === "image"
                anchors.top: rcTabs.bottom
                width: parent.width; height: 28
                color: Theme.panelHeader
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 8
                    text: (root.nodeById(root.selectedNode) ? root.nodeById(root.selectedNode).title : "") + ".Output Image"
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary
                }
                Row {
                    anchors.right: parent.right; anchors.rightMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4
                    Repeater {
                        model: [ { icon: "layers", name: "viewOverlays", tip: "Show / hide result overlays" },
                                 { icon: "search", name: "viewZoomIn",   tip: "Zoom in (or scroll the mouse wheel over the image)" },
                                 { icon: "fit",    name: "viewFit",      tip: "Fit the whole image to the viewer" },
                                 { icon: "roi",    name: "viewResetRoi", tip: "Reset this module's ROI to the whole image (Ctrl+Shift+R)" },
                                 { icon: "target", name: "viewCrosshair", tip: "Show / hide the centre crosshair" },
                                 { icon: "grid",   name: "viewGrid",     tip: "Show / hide a measuring grid (50 px)" } ]
                        delegate: Rectangle {
                            id: vbtn
                            objectName: modelData.name
                            width: 24; height: 22; radius: 3
                            // `viewFit` reads as active when the image is already fitted, so
                            // pressing it gives visible feedback instead of appearing inert.
                            readonly property bool active: modelData.name === "viewOverlays" ? root.layers.overlays === true
                                                         : modelData.name === "viewCrosshair" ? root.layers.crosshair === true
                                                         : modelData.name === "viewGrid" ? root.layers.pixelgrid === true
                                                         : modelData.name === "viewZoomIn" ? viewport.viewZoom > 1.001
                                                         : modelData.name === "viewFit" ? viewport.viewZoom <= 1.001 : false
                            color: vMouse.containsMouse ? Theme.buttonHover : (active ? Theme.accentDim : "transparent")
                            Icon { anchors.centerIn: parent; name: modelData.icon; size: 16 }
                            ToolTip.visible: vMouse.containsMouse; ToolTip.text: modelData.tip; ToolTip.delay: 500
                            MouseArea {
                                id: vMouse; anchors.fill: parent; hoverEnabled: true
                                onClicked: {
                                    if (modelData.name === "viewOverlays") { if (root.backend) root.backend.setLayer("overlays", !(root.layers.overlays === true)) }
                                    else if (modelData.name === "viewCrosshair") { if (root.backend) root.backend.setLayer("crosshair", !(root.layers.crosshair === true)) }
                                    else if (modelData.name === "viewGrid") { if (root.backend) root.backend.setLayer("pixelgrid", !(root.layers.pixelgrid === true)) }
                                    else if (modelData.name === "viewZoomIn") viewport.zoomBy(1.25, viewport.width / 2, viewport.height / 2)
                                    else if (modelData.name === "viewResetRoi") { if (root.backend) root.backend.resetRoi() }
                                    else viewport.fitView()
                                }
                            }
                        }
                    }
                }
            }
            Rectangle {      // viewport
                id: viewport
                objectName: "viewportRect"
                visible: root.viewTab === "image"
                anchors.top: imgHeader.bottom
                width: parent.width
                // The image block (header, viewer, read-out, strip) and the result block
                // below it split the column 6:4, the same way the canvas and this column
                // split 6:4 horizontally.  A fixed 300 px made the image the smallest thing
                // on screen and left the ratio changing with the window, whereas
                // VisionMaster's image window scales with the window rather than sitting at
                // one height.  The 142 px is the header + read-out + strip + strip header
                // that share the image block with this rectangle.
                height: Math.max(160,
                                 (rightColumn.height - rcTabs.height) * root.imageBlockShare
                                 - imgHeader.height - readout.height
                                 - stripHeader.height - strip.height)
                color: Theme.viewport
                clip: true
                property real viewZoom: 1.0              // 1 = the whole image fits; the image header's zoom buttons and the wheel change it
                property real viewPanX: 0
                property real viewPanY: 0
                function resetView() { viewZoom = 1; viewPanX = 0; viewPanY = 0 }
                // "Fit to screen": the whole image visible and centred.  Same state as zoom 1,
                // named separately because that is what the button and Ctrl+0 mean to a user.
                function fitView() { resetView() }
                readonly property bool fitted: viewZoom <= 1.001
                function zoomBy(f, cx, cy) {             // keep the point under (cx, cy) fixed
                    var nz = Math.max(1, Math.min(16, viewZoom * f))
                    var k = nz / viewZoom
                    viewPanX = viewPanX * k + (cx - width / 2) * (1 - k)
                    viewPanY = viewPanY * k + (cy - height / 2) * (1 - k)
                    viewZoom = nz
                    if (nz <= 1) { viewPanX = 0; viewPanY = 0 }
                }
                Image {
                    id: frame
                    objectName: "viewFrame"
                    x: 10 + viewport.viewPanX - (viewport.width - 20) * (viewport.viewZoom - 1) / 2
                    y: 10 + viewport.viewPanY - (viewport.height - 20) * (viewport.viewZoom - 1) / 2
                    width: (viewport.width - 20) * viewport.viewZoom
                    height: (viewport.height - 20) * viewport.viewZoom
                    fillMode: Image.PreserveAspectFit
                    cache: false
                    source: root.backend ? root.backend.imageUrl : "../images/sample_pcb.png"
                }
                // image pixel <-> screen mapping for the ROI tools
                property int cursorX: -1                 // image pixel under the pointer (-1 = outside)
                property int cursorY: -1
                readonly property real imgScale: frame.implicitWidth > 0 ? frame.paintedWidth / frame.implicitWidth : 1
                readonly property real imgX0: frame.x + (frame.width - frame.paintedWidth) / 2
                readonly property real imgY0: frame.y + (frame.height - frame.paintedHeight) / 2

                Rectangle {          // the selected module's ROI
                    // "Show module ROI" in the Display Setup tab hides it; the colour there
                    // is the one the module's overlays are drawn in.
                    visible: root.roi.length === 4 && frame.implicitWidth > 0
                             && root.displaySetup.roi !== false
                    x: viewport.imgX0 + root.roi[0] * viewport.imgScale
                    y: viewport.imgY0 + root.roi[1] * viewport.imgScale
                    width: root.roi[2] * viewport.imgScale
                    height: root.roi[3] * viewport.imgScale
                    color: "#18" + String(root.displaySetup.colour || "").replace("#", "")
                    border.width: 2
                    border.color: root.displaySetup.colour || Theme.accent
                }
                Rectangle {          // rubber band while drawing
                    id: band
                    visible: false
                    color: "#2200a0ff"
                    border.width: 1
                    border.color: "#00a0ff"
                }
                PinchHandler {
                    id: viewerPinch
                    objectName: "viewerPinch"
                    target: null
                    acceptedDevices: PointerDevice.TouchScreen | PointerDevice.TouchPad
                    minimumScale: 0.001
                    maximumScale: 1000
                    property real lastScale: 1.0
                    property real lastX: 0
                    property real lastY: 0
                    onActiveChanged: { lastScale = 1.0; lastX = centroid.position.x; lastY = centroid.position.y }
                    onActiveScaleChanged: if (active && lastScale > 0) { viewport.zoomBy(activeScale / lastScale, centroid.position.x, centroid.position.y); lastScale = activeScale }
                    onCentroidChanged: if (active && viewport.viewZoom > 1.001) {
                        var limX = (viewport.width - 20) * (viewport.viewZoom - 1) / 2, limY = (viewport.height - 20) * (viewport.viewZoom - 1) / 2
                        viewport.viewPanX = Math.max(-limX, Math.min(limX, viewport.viewPanX + centroid.position.x - lastX))
                        viewport.viewPanY = Math.max(-limY, Math.min(limY, viewport.viewPanY + centroid.position.y - lastY))
                        lastX = centroid.position.x; lastY = centroid.position.y
                    }
                }
                MouseArea {
                    id: roiDraw
                    anchors.fill: parent
                    property real sx: 0
                    property real sy: 0
                    property bool panning: false
                    property bool noRoiPress: false     // pressed on a module that has no region to draw
                    property real px0: 0
                    property real py0: 0
                    acceptedButtons: Qt.AllButtons
                    cursorShape: panning ? Qt.ClosedHandCursor : (root.roi.length === 4 ? Qt.CrossCursor : Qt.ArrowCursor)
                    hoverEnabled: true
                    onExited: viewport.cursorX = -1
                    onWheel: function (w) { viewport.zoomBy(root.wheelFactor(w), w.x, w.y) }
                    onPressed: function (m) {
                        // drag moves a zoomed image: right / middle button always, left button when no ROI is being drawn
                        if (viewport.viewZoom > 1.001 && (m.button !== Qt.LeftButton || root.roi.length !== 4)) {
                            panning = true; px0 = m.x - viewport.viewPanX; py0 = m.y - viewport.viewPanY; return
                        }
                        if (m.button !== Qt.LeftButton) return
                        if (root.roi.length !== 4) { sx = m.x; sy = m.y; noRoiPress = true; return }
                        sx = m.x; sy = m.y; band.x = sx; band.y = sy; band.width = 0; band.height = 0; band.visible = true }
                    onPositionChanged: function (m) {
                        viewport.cursorX = Math.floor((m.x - viewport.imgX0) / viewport.imgScale)
                        viewport.cursorY = Math.floor((m.y - viewport.imgY0) / viewport.imgScale)
                        if (panning) {
                            var limX = (viewport.width - 20) * (viewport.viewZoom - 1) / 2, limY = (viewport.height - 20) * (viewport.viewZoom - 1) / 2
                            viewport.viewPanX = Math.max(-limX, Math.min(limX, m.x - px0))
                            viewport.viewPanY = Math.max(-limY, Math.min(limY, m.y - py0))
                            return
                        }
                        if (!pressed || root.roi.length !== 4) return
                        band.x = Math.min(sx, m.x); band.y = Math.min(sy, m.y)
                        band.width = Math.abs(m.x - sx); band.height = Math.abs(m.y - sy)
                    }
                    onReleased: function (m) {
                        if (panning) { panning = false; return }
                        if (noRoiPress) {
                            noRoiPress = false
                            if (Math.abs(m.x - sx) + Math.abs(m.y - sy) > 8) {
                                var n = root.nodeById(root.selectedNode)
                                root.say((n ? n.title : "This module") + " has no region to draw. Select a module with a region (for example Defect Detection, Template Match, Pixel Count or Intensity Measure).")
                            }
                            return
                        }
                        if (!band.visible) return
                        band.visible = false
                        var s = viewport.imgScale
                        if (s <= 0 || band.width < 6 || band.height < 6) return
                        var x = Math.max(0, Math.round((band.x - viewport.imgX0) / s))
                        var y = Math.max(0, Math.round((band.y - viewport.imgY0) / s))
                        var w = Math.round(band.width / s), h = Math.round(band.height / s)
                        if (root.backend) root.backend.setRoi(x, y, w, h); else root.say("ROI " + [x, y, w, h].join(", "))
                    }
                }
            }
            Rectangle {      // cursor read-out
                id: readout
                visible: root.viewTab === "image"
                anchors.top: viewport.bottom
                width: parent.width; height: 22
                color: Theme.panelHeader
                Text { x: 8; anchors.verticalCenter: parent.verticalCenter; text: (root.nodeById(root.selectedNode) ? root.nodeById(root.selectedNode).title.replace(" ", "_") : "") + ".Output Image"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
                Text { anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: (frame.implicitWidth > 0 ? frame.implicitWidth + " * " + frame.implicitHeight : "--- * ---") + "  |  "
                      + (viewport.cursorX >= 0 && viewport.cursorX < frame.implicitWidth && viewport.cursorY >= 0 && viewport.cursorY < frame.implicitHeight
                         ? "X," + viewport.cursorX + "  Y," + viewport.cursorY + "  |  " + (root.backend ? root.backend.pixelInfo(viewport.cursorX, viewport.cursorY) : "R:0 G:0 B:0")
                         : "X,----  Y,----  |  R:--- G:--- B:---"); font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
            }
            Rectangle {      // image strip header: file name, load buttons, loop, scope, run/stop
                id: stripHeader
                anchors.top: readout.bottom
                width: parent.width; height: 36
                color: Theme.panelHeader
                Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: root.imagePool.length ? root.imagePool[root.imageIndex].name + " (" + (root.imageIndex + 1) + "/" + root.imagePool.length + ")" : "No images"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontLabel; font.weight: Font.DemiBold; color: Theme.textPrimary }
                Row {
                    anchors.right: parent.right; anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Rectangle { width: 24; height: 24; radius: 3; color: addMouse.containsMouse ? "#c8ccd0" : "transparent"; anchors.verticalCenter: parent.verticalCenter
                        Icon { anchors.centerIn: parent; name: "plus"; size: 18 }
                        MouseArea { id: addMouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.invoke("loadImage") } }
                    Rectangle { width: 24; height: 24; radius: 3; color: folderMouse.containsMouse ? "#c8ccd0" : "transparent"; anchors.verticalCenter: parent.verticalCenter
                        Icon { anchors.centerIn: parent; name: "folder"; size: 18 }
                        MouseArea { id: folderMouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.invoke("loadFolder") } }
                    Rectangle { width: 24; height: 24; radius: 3; color: clearMouse.containsMouse ? "#c8ccd0" : "transparent"; anchors.verticalCenter: parent.verticalCenter
                        Icon { anchors.centerIn: parent; name: "close"; size: 16 }
                        MouseArea { id: clearMouse; anchors.fill: parent; hoverEnabled: true; onClicked: if (root.backend) root.backend.clearImages() } }
                    Text { text: "Loop"; anchors.verticalCenter: parent.verticalCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    ToggleSwitch { x: 110; anchors.verticalCenter: parent.verticalCenter; checked: root.loopOn; onToggled: function (value) { root.setLoop(value) } }
                    SelectBox { width: 112; color: "#00ffffff"; model: root.scopes; anchors.verticalCenter: parent.verticalCenter; onActivated: if (root.backend) root.backend.setScope(currentText) }
                    AppButton {
                        width: 84
                        text: root.running ? "Stop" : "Run"
                        icon: root.running ? "stop" : "run"
                        kind: root.running ? "stop" : "run"
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: if (root.backend) (root.running ? root.backend.stop() : root.backend.run())
                    }
                }
            }
            Rectangle {      // thumbnails
                id: strip
                anchors.top: stripHeader.bottom
                width: parent.width; height: 56
                color: Theme.rail
                Row {
                    x: 10; anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Repeater {
                        model: root.imagePool
                        delegate: Rectangle {
                            width: 62; height: 44
                            color: Theme.viewport
                            border.width: index === root.imageIndex ? 2 : 1
                            border.color: index === root.imageIndex ? Theme.accent : "#888"
                            Image { anchors.fill: parent; anchors.margins: 2; fillMode: Image.PreserveAspectFit; asynchronous: true; sourceSize.width: 124; source: modelData.url }
                            MouseArea { anchors.fill: parent; onClicked: if (root.backend) root.backend.selectImage(index) }
                        }
                    }
                }
            }

            // result tabs + table
            Row {
                id: resTabs
                anchors.top: strip.bottom
                Repeater {
                    model: ["Current Result", "History", "Help"]
                    delegate: TabButton2 { text: modelData; selected: root.resultTab === index; onClicked: root.resultTab = index }
                }
            }
            Column {
                objectName: "currentResultPane"
                visible: root.resultTab === 0
                anchors.top: resTabs.bottom
                anchors.bottom: parent.bottom
                width: parent.width
                Text {
                    x: 8; y: 6
                    text: (root.nodeById(root.selectedNode) ? root.nodeById(root.selectedNode).title : "") + " · " + (root.nodeById(root.selectedNode) ? root.nodeById(root.selectedNode).status : root.verdict)
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.DemiBold; color: Theme.textPrimary
                }
                Item { width: 1; height: 12 }
                Rectangle { width: parent.width; height: 26; color: Theme.panelHeader
                    Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "Parameter"; font.pixelSize: Theme.fontBody; font.family: Theme.fontFamily; color: Theme.textSecondary }
                    Text { x: 190; anchors.verticalCenter: parent.verticalCenter; text: "Value"; font.pixelSize: Theme.fontBody; font.family: Theme.fontFamily; color: Theme.textSecondary }
                }
                Repeater {
                    model: root.results
                    delegate: Rectangle {
                        width: parent.width; height: 26
                        color: index % 2 ? "#f1f4f5" : Theme.panelAlt
                        Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.name; font.pixelSize: Theme.fontBody; font.family: Theme.fontFamily; color: Theme.textPrimary }
                        Text { x: 190; anchors.verticalCenter: parent.verticalCenter; text: modelData.value; font.pixelSize: Theme.fontBody; font.family: Theme.monoFamily; color: Theme.textPrimary }
                    }
                }
            }
            Item {           // History tab: one line per finished run, newest first
                id: historyPane
                objectName: "historyPane"
                visible: root.resultTab === 1
                anchors.top: resTabs.bottom
                anchors.bottom: parent.bottom
                width: parent.width
                Rectangle {
                    id: hHead
                    width: parent.width; height: 26
                    color: Theme.panelHeader
                    Text { x: 10;  anchors.verticalCenter: parent.verticalCenter; text: "#";       font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 44;  anchors.verticalCenter: parent.verticalCenter; text: "Time";    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 118; anchors.verticalCenter: parent.verticalCenter; text: "Source";  font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 300; anchors.verticalCenter: parent.verticalCenter; text: "Result";  font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 362; anchors.verticalCenter: parent.verticalCenter; text: "Flow";    font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { x: 440; anchors.verticalCenter: parent.verticalCenter; text: "Failed modules"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text {
                        objectName: "historyClear"
                        anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                        text: "Clear"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.underline: true; color: Theme.textMuted
                        MouseArea { anchors.fill: parent; anchors.margins: -6; onClicked: if (root.backend) root.backend.clearHistory() }
                    }
                }
                ListView {
                    objectName: "historyList"
                    anchors.top: hHead.bottom
                    anchors.bottom: parent.bottom
                    width: parent.width
                    clip: true
                    model: root.runHistory
                    delegate: Rectangle {
                        width: ListView.view.width; height: 26
                        color: index % 2 ? "#f1f4f5" : Theme.panelAlt
                        Text { x: 10;  anchors.verticalCenter: parent.verticalCenter; text: modelData.n;    font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
                        Text { x: 44;  anchors.verticalCenter: parent.verticalCenter; text: modelData.time; font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textPrimary }
                        Text { x: 118; width: 174; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.source
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                        Text { x: 300; anchors.verticalCenter: parent.verticalCenter; text: modelData.verdict
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; font.weight: Font.Bold
                               color: modelData.verdict === "PASS" ? Theme.okText : Theme.errorText }
                        Text { x: 362; anchors.verticalCenter: parent.verticalCenter; text: modelData.flowMs.toFixed(1) + " ms"
                               font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textPrimary }
                        Text { x: 440; width: 190; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.failed
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.errorText }
                    }
                    Text {
                        visible: root.runHistory.length === 0
                        anchors.centerIn: parent
                        text: "No runs yet. Press Run."
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textMuted
                    }
                }
            }
            Flickable {      // Help tab: what the selected module is and what its settings mean
                id: helpPane
                objectName: "helpPane"
                visible: root.resultTab === 2
                anchors.top: resTabs.bottom
                anchors.bottom: parent.bottom
                width: parent.width
                clip: true
                contentWidth: width
                contentHeight: helpColumn.height + 16
                Column {
                    id: helpColumn
                    x: 10; y: 8
                    width: parent.width - 20
                    spacing: 6
                    Text { width: parent.width; wrapMode: Text.WordWrap
                           text: root.helpInfo.title ? root.helpInfo.title : "Select a module to see its help"
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody + 2; font.weight: Font.DemiBold; color: Theme.textPrimary }
                    Text { visible: !!root.helpInfo.tool; width: parent.width
                           text: (root.helpInfo.tool || "") + "  ·  " + (root.helpInfo.category || "")
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
                    Text { visible: !!root.helpInfo.description; width: parent.width; wrapMode: Text.WordWrap; text: root.helpInfo.description || ""
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                    Text { visible: !!(root.helpInfo.inputs && root.helpInfo.inputs.length); width: parent.width; wrapMode: Text.WordWrap
                           text: "Inputs: " + (root.helpInfo.inputs || []).join(",  ")
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Text { visible: !!(root.helpInfo.outputs && root.helpInfo.outputs.length); width: parent.width; wrapMode: Text.WordWrap
                           text: "Outputs: " + (root.helpInfo.outputs || []).join(",  ")
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    Rectangle { visible: !!(root.helpInfo.parameters && root.helpInfo.parameters.length); width: parent.width; height: 24; color: Theme.panelHeader
                        Text { x: 6;   anchors.verticalCenter: parent.verticalCenter; text: "Setting";       font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                        Text { x: 200; anchors.verticalCenter: parent.verticalCenter; text: "Current value"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                        Text { x: 330; anchors.verticalCenter: parent.verticalCenter; text: "Allowed";       font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textSecondary }
                    }
                    Repeater {
                        model: root.helpInfo.parameters || []
                        delegate: Rectangle {
                            width: helpColumn.width; height: 26
                            color: index % 2 ? "#f1f4f5" : Theme.panelAlt
                            Text { x: 6;   width: 188; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.name
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary }
                            Text { x: 200; width: 124; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.value
                                   font.family: Theme.monoFamily; font.pixelSize: Theme.fontCaption; color: Theme.textPrimary }
                            Text { x: 330; width: 280; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideRight; text: modelData.limits
                                   font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
                        }
                    }
                }
            }
        }
    }

    // ================================ STATUS BAR =======================================
    Rectangle {
        id: statusBar
        anchors.bottom: parent.bottom
        width: parent.width
        height: Theme.statusBarHeight
        // The darker chrome with light ink, matching the toolbars.  It was the light
        // menu-strip grey filled with `Theme.textPrimary` - dark ink on a mid-grey,
        // measured 3.06:1, below the 4.5:1 the rest of the interface holds to.
        color: Theme.chromeDark
        Text { x: 16; width: parent.width - 520; elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter; text: root.toast !== "" ? root.toast : root.hint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textOnChrome }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            spacing: 26
            Text { text: "Flow " + root.flowMs.toFixed(2) + "ms"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textOnChrome }
            Text { text: "Tools " + root.toolCount; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textOnChrome }
            Text { text: "Algorithm " + root.algoMs.toFixed(2) + "ms"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontBody; color: Theme.textOnChrome }
            Text { text: "v" + (backend ? backend.version : ""); font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textOnChrome }
        }
    }

    // ================================ SHORTCUTS ========================================
    Shortcut { sequence: "Ctrl+N"; onActivated: root.invoke("newSolution") }
    Shortcut { sequence: "Ctrl+O"; onActivated: root.invoke("openSolution") }
    Shortcut { sequence: "Ctrl+S"; onActivated: root.invoke("save") }
    Shortcut { sequence: "Ctrl+Shift+S"; onActivated: root.invoke("saveAs") }
    Shortcut { sequence: "Ctrl+I"; onActivated: root.invoke("loadImage") }
    // Reset the selected module's ROI back to the whole image.  Ctrl+0 fits the canvas, so
    // the ROI reset needs its own binding.
    Shortcut { sequence: "Ctrl+Shift+R"; onActivated: if (root.backend) root.backend.resetRoi() }
    Shortcut { sequence: "Ctrl+Z"; onActivated: if (root.backend) root.backend.undo() }
    Shortcut { sequence: "Ctrl+Y"; onActivated: if (root.backend) root.backend.redo() }
    Shortcut { sequence: "Ctrl+1"; onActivated: root.invoke("viewFlow") }
    Shortcut { sequence: "Ctrl+2"; onActivated: root.invoke("viewOperation") }
    Shortcut { sequence: "Ctrl+3"; onActivated: root.invoke("viewMulti") }
    Shortcut { sequence: "Ctrl+0"; onActivated: root.fitView() }
    Shortcut { sequence: "F1"; onActivated: root.invoke("manual") }

    // ================================ OVERLAYS =========================================
    ToolFlyout {
        visible: root.railCategory >= 0
        category: root.railCategory >= 0 && root.railCategory < root.categories.length ? root.categories[root.railCategory] : root.categories[0]
        categories: root.categories
        x: Theme.railWidth
        y: menuBar.height + toolbar1.height + toolbar2.height
        height: body.height
        z: 20
        onToolChosen: function (name) { if (root.backend) root.backend.addTool(name); else root.say("Added " + name); root.railCategory = -1 }
    }

    AiChatPanel {
        id: aiPanel
        objectName: "aiPanel"
        visible: root.aiVisible
        x: root.width - width - 16
        y: menuBar.height + toolbar1.height + toolbar2.height + 12
        z: 45
        onCloseRequested: root.aiVisible = false
    }
    Shortcut { sequence: "Ctrl+G"; onActivated: root.invoke("aiGen") }

    InspectionPanel {
        visible: root.inspectionVisible
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: statusBar.top
        height: 330
        tab: root.inspectionTab
        z: 30
        onCloseRequested: root.inspectionVisible = false
    }

    Connections {                // closing a dialog hands the keyboard back to the flow canvas
        target: dialogs
        function onCurrentChanged() {
            if (dialogs.current === "" && !root.aiVisible && root.workspaceTab === 0) Qt.callLater(function () { canvas.forceActiveFocus() })
        }
    }

    DialogHost {
        id: dialogs
        anchors.fill: parent
        z: 100
        onProjectCreated: if (root.backend) root.backend.workspaceRequested()
    }

    FileDialog {
        id: openDialog
        title: "Open Solution File"
        nameFilters: ["Apex Solution (*.apex *.xml *.vmp *.sol *.json)", "All files (*)"]
        onAccepted: if (root.backend) root.backend.openRecent(backend.urlToPath(selectedFile.toString()))
    }
    FileDialog {
        id: saveDialog
        title: "Save Solution As"
        fileMode: FileDialog.SaveFile
        nameFilters: ["Apex Project (*.apex)", "Solution XML (*.xml)", "Solution JSON (*.json)"]
        onAccepted: if (root.backend) root.backend.saveProjectAs(backend.urlToPath(selectedFile.toString()))
    }
    FileDialog {
        id: imageDialog
        title: "Add / Load Image Files to Flow"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)", "All files (*)"]
        onAccepted: if (root.backend) root.backend.loadImageFiles(selectedFiles.map(function (u) { return u.toString() }))
    }
    FileDialog {
        id: csvDialog
        title: "Export Results to CSV"
        fileMode: FileDialog.SaveFile
        nameFilters: ["CSV files (*.csv)"]
        defaultSuffix: "csv"
        onAccepted: if (root.backend) root.backend.exportResultsCsv(selectedFile.toString())
    }
    FileDialog {
        id: xmlExportDialog
        title: "Export Flow as XML"
        fileMode: FileDialog.SaveFile
        nameFilters: ["XML flow files (*.xml)"]
        defaultSuffix: "xml"
        onAccepted: if (root.backend) root.backend.exportFlowXml(selectedFile.toString())
    }
    FileDialog {
        id: xmlImportDialog
        title: "Import Flow from XML"
        nameFilters: ["XML flow files (*.xml)", "All files (*)"]
        onAccepted: if (root.backend) root.backend.importFlowXml(selectedFile.toString())
    }
    FolderDialog {
        id: datasetFolderDialog
        title: "Choose a folder for the sample defect dataset"
        onAccepted: if (typeof appInspection !== "undefined") { appInspection.generateDataset(selectedFolder.toString(), 40); inspectionTab = 0; inspectionVisible = true }
    }
    FolderDialog {
        id: folderDialog
        title: "Load All Images From Folder"
        onAccepted: if (root.backend) root.backend.loadImageFolder(selectedFolder.toString())
    }
}
