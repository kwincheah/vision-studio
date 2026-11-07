import QtQuick 2.15
import ApexTheme 1.0

// Caption above a field - used by dialogs.  Put the field inside as a child.
Column {
    id: root
    property string label: "Label"
    default property alias content: holder.data
    spacing: Theme.spTight

    Text {
        text: root.label
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontLabel
        font.weight: Font.DemiBold
        color: Theme.textPrimary
    }
    Item {
        id: holder
        width: root.width
        height: childrenRect.height
    }
}
