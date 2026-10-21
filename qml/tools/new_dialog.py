"""Scaffold a new QML dialog and register it everywhere it must be listed.

    python qml/tools/new_dialog.py SettingsHub "Settings Hub" [--menu Settings] [--text "Settings Hub..."]

Creates   qml/ApexDialogs/SettingsHubDialog.qml          (DialogFrame skeleton with backend fallback)
Edits     qml/ApexDialogs/qmldir                          (component registration)
          qml/ApexDialogs/DialogHost.qml                  (instance, shown by name)
          qml/ApexTheme/SampleData.qml                    (menu entry, when --menu is given)
          qml/screens/MainScreen.qml                      (invoke() case that opens it)
Prints the Python backend stub to paste into apex_vision/qml_backend.py.
Safe to re-run: anything already registered is left alone.
"""
import argparse
import os
import re
import sys

QML = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

TEMPLATE = '''import QtQuick 2.15
import ApexTheme 1.0
import ApexComponents 1.0

// {title}
DialogFrame {{
    id: root
    readonly property var backend: typeof appBackend !== "undefined" ? appBackend : null
    title: "{title}"
    dialogWidth: 560
    dialogHeight: 380

    Column {{
        anchors.fill: parent
        spacing: 12
        Text {{
            text: "Describe what this dialog does."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.textSecondary
        }}
        FormRow {{
            label: "Name:"
            width: parent.width
            TextBox {{ id: nameField; width: parent.width; placeholder: "Type here" }}
        }}
    }}
    buttons: [
        AppButton {{ text: "Cancel"; width: 90; onClicked: root.closed() }},
        AppButton {{ text: "OK"; kind: "primary"; width: 90
            onClicked: {{ if (root.backend) root.backend.{slot}(nameField.text); root.closed() }} }}
    ]
}}
'''


def read(rel):
    with open(os.path.join(QML, rel), encoding="utf-8") as fh:
        return fh.read()


def write(rel, text):
    with open(os.path.join(QML, rel), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="CamelCase name without the 'Dialog' suffix, e.g. SettingsHub")
    ap.add_argument("title", help="window title, e.g. 'Settings Hub'")
    ap.add_argument("--menu", help="add a menu entry under this top-level menu (File, Tools, ...)")
    ap.add_argument("--text", help="menu entry text (default: title + '...')")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", args.name):
        print("name must be CamelCase letters/digits, e.g. SettingsHub")
        return 2
    comp = f"{args.name}Dialog"
    key = args.name[0].lower() + args.name[1:]
    slot = "apply" + args.name
    path = os.path.join(QML, "ApexDialogs", f"{comp}.qml")
    done = []

    if os.path.exists(path):
        print(f"= {comp}.qml already exists - left untouched")
    else:
        write(f"ApexDialogs/{comp}.qml", TEMPLATE.format(title=args.title, slot=slot))
        done.append(f"created ApexDialogs/{comp}.qml")

    qmldir = read("ApexDialogs/qmldir")
    if comp not in qmldir:
        qmldir = qmldir.replace("DialogHost 1.0", f"{comp} 1.0 {comp}.qml\nDialogHost 1.0")
        write("ApexDialogs/qmldir", qmldir)
        done.append("registered in ApexDialogs/qmldir")

    host = read("ApexDialogs/DialogHost.qml")
    if f'"{key}"' not in host:
        line = (f'    {comp} {{ anchors.fill: parent; visible: host.current === "{key}"; '
                f'onClosed: host.close() }}\n')
        host = host.rstrip()
        host = host[:host.rfind("}")] + line + "}\n"
        write("ApexDialogs/DialogHost.qml", host)
        done.append("added to DialogHost.qml")

    if args.menu:
        data = read("ApexTheme/SampleData.qml")
        text = args.text or f"{args.title}..."
        if f'key: "{key}"' in data:
            print(f"= menu entry for {key} already exists")
        else:
            m = re.search(r'\{ title: "%s", items: \[' % re.escape(args.menu), data)
            if not m:
                print(f"! menu '{args.menu}' not found in SampleData.qml - add the entry by hand")
            else:
                entry = f'\n            {{ text: "{text}", key: "{key}" }},'
                data = data[:m.end()] + entry + data[m.end():]
                write("ApexTheme/SampleData.qml", data)
                done.append(f"menu entry under {args.menu}")

    main_qml = read("screens/MainScreen.qml")
    if f'case "{key}"' not in main_qml:
        marker = '        case "flowSettings":'
        if marker in main_qml:
            main_qml = main_qml.replace(marker, f'        case "{key}": dialogs.show("{key}"); break\n{marker}', 1)
            write("screens/MainScreen.qml", main_qml)
            done.append("invoke() case in MainScreen.qml")
        else:
            print('! could not find the invoke() switch - add:  case "%s": dialogs.show("%s"); break' % (key, key))

    for line in done:
        print("+", line)
    print(f"""
Next - add this to apex_vision/qml_backend.py (inside AppBackend):

    @pyqtSlot(str)
    def {slot}(self, value):
        self._push_undo()                      # makes the change undoable
        # ... call the engine here (reuse apex_vision/core, do not copy logic) ...
        self._notify("{args.title}: done")

Preview: open qml/ApexVision.qmlproject in Qt Design Studio and set DialogHost.current = "{key}".""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
