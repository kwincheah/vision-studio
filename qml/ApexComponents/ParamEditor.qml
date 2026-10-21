import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Dialogs
import ApexTheme 1.0

/*
 * Editor for one module parameter, chosen by its kind (see apex_vision/core/param_schema.py):
 *   bool -> switch      enum -> drop-down      combo -> drop-down + typed value     int / float -> number with limits
 *   rect / point / line / rgb -> labelled number fields      points -> one "x, y" per line
 *   path / dir -> text + Browse      code -> multi-line editor      device / flow -> drop-down of what exists
 *   text -> text box
 * `spec` is a row of backend.moduleParams(); `edited(value)` carries a JS value of the parameter's own type.
 */
Item {
    id: root
    property var spec: ({ kind: "text", native: "", name: "param", label: "Param" })
    signal edited(var value)

    readonly property string kind: spec.kind
    readonly property var val: spec.native
    implicitWidth: 360
    implicitHeight: loader.item ? loader.item.implicitHeight : 26
    height: implicitHeight

    function withItem(list, i, v) { var c = list.slice(); c[i] = v; return c }

    Loader {
        id: loader
        width: parent.width
        sourceComponent: {
            switch (root.kind) {
            case "bool": return boolEditor
            case "enum": case "device": case "flow": return root.spec.choices && root.spec.choices.length ? enumEditor : textEditor
            case "combo": return comboEditor
            case "int": case "float": return numberEditor
            case "rect": case "point": case "line": case "rgb": return tupleEditor
            case "points": return pointsEditor
            case "code": return codeEditor
            case "path": case "dir": return pathEditor
            default: return textEditor
            }
        }
    }

    Component { id: boolEditor
        Item { implicitHeight: 26
            ToggleSwitch { objectName: "paramSwitch"; anchors.verticalCenter: parent.verticalCenter; checked: root.val === true
                onToggled: function (value) { root.edited(value) } }
        }
    }

    Component { id: enumEditor
        SelectBox { objectName: "paramEnum"; width: Math.min(root.width, 260)
            model: root.spec.choices
            currentIndex: Math.max(0, root.spec.choices.indexOf(root.val))
            onActivated: function (i) { root.edited(root.spec.choices[i]) } }
    }

    Component { id: comboEditor
        Row { spacing: Theme.spSnug
            SelectBox { id: pick; objectName: "paramEnum"; width: 150; model: root.spec.choices
                currentIndex: Math.max(0, root.spec.choices.indexOf(root.val))
                onActivated: function (i) { typed.text = root.spec.choices[i]; root.edited(root.spec.choices[i]) } }
            TextBox { id: typed; objectName: "paramText"; width: Math.max(120, root.width - 160); text: String(root.val)
                onEditingFinished: if (text !== String(root.val)) root.edited(text) }
        }
    }

    Component { id: numberEditor
        Row { spacing: Theme.spSnug
            NumberBox { objectName: "paramNumber"; width: 190
                value: Number(root.val)
                from: root.spec.min !== undefined ? root.spec.min : -1e12
                to: root.spec.max !== undefined ? root.spec.max : 1e12
                step: root.spec.step !== undefined ? root.spec.step : 1
                decimals: root.spec.decimals !== undefined ? root.spec.decimals : 0
                suffix: root.spec.unit || ""
                onEdited: function (v) { root.edited(root.kind === "int" ? Math.round(v) : v) } }
            Text { visible: root.spec.min !== undefined && root.spec.min > -1e11 && root.spec.max < 1e11; anchors.verticalCenter: parent.verticalCenter
                text: root.spec.min + " to " + root.spec.max
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
        }
    }

    Component { id: tupleEditor
        Flow { id: tuple; spacing: Theme.spBase
            readonly property var labels: root.kind === "rect" ? ["X", "Y", "W", "H"] : root.kind === "line" ? ["X1", "Y1", "X2", "Y2"] : root.kind === "rgb" ? ["R", "G", "B"] : ["X", "Y"]
            readonly property bool whole: root.val.every(function (n) { return Math.round(n) === n })
            Repeater { model: tuple.labels.length
                delegate: Row { spacing: 3
                    Text { width: 16; height: 26; verticalAlignment: Text.AlignVCenter; text: tuple.labels[index]
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textSecondary }
                    NumberBox { objectName: "paramTuple" + index; width: 84
                        value: Number(root.val[index]); decimals: tuple.whole ? 0 : 2; step: tuple.whole ? 1 : 0.5
                        from: root.kind === "rgb" ? 0 : (root.kind === "rect" && index > 1 ? 1 : (root.kind === "rgb" ? 0 : (root.kind === "point" || root.kind === "line" || root.kind === "rect" ? 0 : -1e12)))
                        to: root.kind === "rgb" ? 255 : 10000000
                        onEdited: function (v) { root.edited(root.withItem(root.val, index, v)) } }
                }
            }
            Rectangle { visible: root.kind === "rgb"; width: 26; height: 26; radius: Theme.radiusControl; border.width: 1; border.color: Theme.fieldBorder
                color: Qt.rgba(root.val[0] / 255, root.val[1] / 255, root.val[2] / 255, 1) }
        }
    }

    Component { id: pointsEditor
        Column { id: pts; spacing: Theme.spSnug
            function parse() {
                var rows = area.text.split("\n"), out = []
                for (var i = 0; i < rows.length; i++) {
                    if (rows[i].trim() === "") continue
                    var parts = rows[i].split(/[,;\s]+/).filter(function (x) { return x !== "" })
                    if (parts.length !== 2 || isNaN(Number(parts[0])) || isNaN(Number(parts[1]))) { err.text = "Line " + (i + 1) + ": write x, y"; return null }
                    out.push([Number(parts[0]), Number(parts[1])])
                }
                err.text = ""
                return out
            }
            Rectangle { width: Math.min(root.width, 260); height: 96; color: Theme.fieldBg; border.width: 1
                border.color: area.activeFocus ? Theme.primary : Theme.fieldBorder; radius: Theme.radiusPanel
                Flickable { anchors.fill: parent; anchors.margins: 4; contentHeight: area.contentHeight; clip: true
                    TextEdit { id: area; objectName: "paramPoints"; width: parent.width
                        text: root.val.map(function (p) { return p[0] + ", " + p[1] }).join("\n")
                        font.family: Theme.monoFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary; selectByMouse: true; activeFocusOnTab: true } } }
            Row { spacing: Theme.spBase
                AppButton { text: "Apply points"; width: 110; onClicked: { var p = pts.parse(); if (p) root.edited(p) } }
                Text { id: err; anchors.verticalCenter: parent.verticalCenter; font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.errorText }
                Text { visible: err.text === ""; anchors.verticalCenter: parent.verticalCenter; text: "one x, y per line"
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontCaption; color: Theme.textMuted }
            }
        }
    }

    Component { id: codeEditor
        Column { spacing: Theme.spSnug
            Rectangle { width: root.width; height: 170; color: Theme.fieldBg; border.width: 1
                border.color: code.activeFocus ? Theme.primary : Theme.fieldBorder; radius: Theme.radiusPanel
                Flickable { anchors.fill: parent; anchors.margins: 4; contentHeight: code.contentHeight; contentWidth: code.contentWidth; clip: true
                    TextEdit { id: code; objectName: "paramCode"; text: String(root.val); width: Math.max(contentWidth, parent.width)
                        font.family: Theme.monoFamily; font.pixelSize: Theme.fontBody; color: Theme.textPrimary; selectByMouse: true; activeFocusOnTab: true } } }
            AppButton { text: "Apply script"; width: 110; onClicked: root.edited(code.text) }
        }
    }

    Component { id: pathEditor
        Row { spacing: Theme.spSnug
            TextBox { id: pathBox; objectName: "paramText"; width: Math.max(120, root.width - 90); text: String(root.val)
                onEditingFinished: if (text !== String(root.val)) root.edited(text) }
            AppButton { text: "Browse..."; width: 82; onClicked: root.kind === "dir" ? folderPick.open() : filePick.open() }
            FileDialog { id: filePick; title: "Choose " + root.spec.label; nameFilters: (root.spec.filters || "All files (*)").split(";;")
                onAccepted: { var p = selectedFile.toString().replace(/^file:\/\/\//, ""); pathBox.text = p; root.edited(p) } }
            FolderDialog { id: folderPick; title: "Choose " + root.spec.label
                onAccepted: { var p = selectedFolder.toString().replace(/^file:\/\/\//, ""); pathBox.text = p; root.edited(p) } }
        }
    }

    Component { id: textEditor
        TextBox { objectName: "paramText"; width: root.width; text: String(root.val); placeholder: root.spec.hint || ""
            onEditingFinished: if (text !== String(root.val)) root.edited(text) }
    }
}
