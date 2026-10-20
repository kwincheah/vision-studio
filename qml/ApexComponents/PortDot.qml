import QtQuick 2.15
import ApexTheme 1.0

// Connection point on a module card.  dataType colours it: image / value / region / string.
Rectangle {
    id: root
    property string dataType: "value"
    width: 9
    height: 9
    radius: 2
    color: "#ffffff"
    border.width: 2
    border.color: dataType === "image" ? "#2b7bb9" : dataType === "value" ? "#e4a020"
                : dataType === "string" ? "#8a5bd0" : "#2f9e5a"
}
