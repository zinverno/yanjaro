pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
RowLayout {
    id: links
    required property var music
    required property var rowData
    property bool showAlbum: false
    spacing: Theme.small
    Button {
        id: artist
        objectName: "artistLink"
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        implicitHeight: 22
        padding: 0
        flat: true
        text: links.rowData.artist || links.rowData.detail || ""
        enabled: (links.rowData.artists || []).length > 0
        Accessible.name: "Открыть исполнителя: " + text
        contentItem: Label { text: artist.text; color: artist.hovered ? Theme.accent : Theme.secondary; font.pixelSize: Theme.caption; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; textFormat: Text.PlainText }
        background: Rectangle { color: "transparent"; border.width: artist.visualFocus ? 1 : 0; border.color: Theme.accent; radius: 3 }
        onClicked: {
            if (links.rowData.artists.length === 1) links.music.open_entity("artist", links.rowData.artists[0].id)
            else artists.open()
        }
        Menu {
            id: artists
            Repeater {
                model: links.rowData.artists || []
                MenuItem { required property var modelData; text: modelData.title; onTriggered: links.music.open_entity("artist", modelData.id) }
            }
        }
    }
    Button {
        id: album
        objectName: "albumLink"
        visible: links.showAlbum && Boolean(links.rowData.albumId) && links.width > 280
        Layout.fillWidth: true
        implicitHeight: 22
        padding: 0
        flat: true
        text: links.rowData.albumTitle || "Альбом"
        Accessible.name: "Открыть альбом: " + text
        ToolTip.visible: hovered; ToolTip.text: text
        contentItem: Label { text: album.text; color: album.hovered ? Theme.accent : Theme.secondary; font.pixelSize: Theme.caption; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; textFormat: Text.PlainText }
        background: Rectangle { color: "transparent"; border.width: album.visualFocus ? 1 : 0; border.color: Theme.accent; radius: 3 }
        onClicked: links.music.open_entity("album", links.rowData.albumId)
    }
}
