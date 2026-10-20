import QtQuick 2.15

// An icon from images/<tone>/<name>.svg.  tone: "light" (on chrome), "dark" (on panels),
// "accent" or "white".
Item {
    id: root
    property string name: "save"
    property string tone: "dark"
    property int size: 18
    implicitWidth: size
    implicitHeight: size

    Image {
        anchors.centerIn: parent
        width: root.size
        height: root.size
        sourceSize: Qt.size(root.size * 2, root.size * 2)
        source: root.name === "" ? "" : "../images/" + root.tone + "/" + root.name + ".svg"
        smooth: true
    }
}
