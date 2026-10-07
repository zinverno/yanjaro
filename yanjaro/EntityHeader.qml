pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: header
    required property var music
    required property var viewState
    property var info: music.content.meta
    RowLayout {
        Layout.fillWidth: true
        Artwork { url: header.info.cover || ""; Layout.preferredWidth: 68; Layout.preferredHeight: 68 }
        ColumnLayout {
            Layout.fillWidth: true
            Label { text: [header.info.artist || "", header.info.year || ""].filter(Boolean).join(" · "); textFormat: Text.PlainText; color: Theme.secondary; elide: Text.ElideRight; Layout.fillWidth: true }
            RowLayout {
                ActionButton { text: header.viewState.entityKind === "album" ? "Слушать" : "Слушать загруженные треки"; symbol: "play"; primary: true; enabled: header.music.content.rows.some(r => r.kind === "track" && r.available); onClicked: header.music.play_page() }
                ActionButton { visible: header.viewState.entityKind === "artist"; text: "Все альбомы"; onClicked: header.music.open_entity("artist-albums", header.info.id) }
            }
        }
    }
    Flickable {
        visible: (header.info.albums || []).length > 0
        Layout.fillWidth: true
        implicitHeight: visible ? 58 : 0
        contentWidth: releases.implicitWidth; contentHeight: height
        clip: true
        Row {
            id: releases
            spacing: Theme.small
            Repeater {
                model: header.info.albums || []
                ActionButton { required property var modelData; width: 190; height: 48; text: modelData.title; contentItem: Label { text: parent.text; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter; textFormat: Text.PlainText } onClicked: header.music.open_entity("album", modelData.id) }
            }
        }
    }
}
