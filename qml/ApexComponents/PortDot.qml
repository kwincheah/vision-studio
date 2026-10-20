import QtQuick 2.15
import ApexTheme 1.0

// Connection point on a module card.  dataType colours it: image / value / region / string.
Rectangle {
    id: root
    property string dataType: "value"
    property string dtype: ""            // exact engine type (IMAGE, VALUE, POINT ...): drives colour and compatibility
    property bool hot: false             // pointer over the port, or it is the snapped target of a wire
    property bool dim: false             // a wire is being dragged and this port cannot take it
    width: 9
    height: 9
    radius: 2
    color: hot ? border.color : "#ffffff"
    scale: hot ? 1.45 : 1
    opacity: dim ? 0.35 : 1
    Behavior on scale { NumberAnimation { duration: 90 } }
    border.width: 2
    border.color: Theme.portColor(dtype, dataType)
}
