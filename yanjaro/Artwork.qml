import QtQuick
Rectangle {
    id: art
    property string url: ""
    property string fallback: "music"
    implicitWidth: 44
    implicitHeight: 44
    radius: Theme.radius / 2
    color: "#88917f"
    Image {
        anchors.centerIn: parent
        width: parent.width * 0.46
        height: width
        source: "icons/" + art.fallback + ".svg"
        visible: cover.status !== Image.Ready
    }
    Image {
        id: cover
        anchors.fill: parent
        source: art.url
        asynchronous: true
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: 100
        sourceSize.height: 100
        visible: status === Image.Ready
    }
}
