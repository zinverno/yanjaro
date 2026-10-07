import QtQuick
import QtQuick.Controls
Button {
    id: control
    property string symbol: ""
    property bool primary: false
    property bool selected: false
    property bool iconOnly: false
    implicitHeight: Theme.button
    implicitWidth: iconOnly ? Theme.button : Math.max(Theme.button, implicitContentWidth + 28)
    display: iconOnly ? AbstractButton.IconOnly : AbstractButton.TextBesideIcon
    icon.source: symbol ? Qt.resolvedUrl("icons/" + symbol + ".svg") : ""
    icon.width: 18
    icon.height: 18
    icon.color: primary ? Theme.accentText : Theme.text
    palette.buttonText: primary ? Theme.accentText : Theme.text
    font.pixelSize: Theme.body
    spacing: Theme.small
    opacity: enabled ? 1 : 0.4
    Accessible.name: text
    ToolTip.text: text
    ToolTip.visible: hovered && iconOnly
    ToolTip.delay: 600
    background: Rectangle {
        radius: Theme.radius
        color: control.down ? Theme.line : control.primary ? Theme.accent :
               control.hovered ? Theme.hover : control.selected ? Theme.selected : "transparent"
        border.width: control.visualFocus ? 2 : control.selected ? 1 : 0
        border.color: Theme.accent
    }
}
