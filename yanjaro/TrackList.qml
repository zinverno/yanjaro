pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ListView {
    id: list
    required property var music
    required property var viewState
    property string pageKey: music.content.view
    property bool restoring: false
    objectName: "tracksList"
    clip: true
    reuseItems: true
    cacheBuffer: Theme.track * 4
    model: music.content.rows
    currentIndex: -1
    ScrollBar.vertical: ScrollBar {}
    function restore() {
        restoring = true
        Qt.callLater(function() {
            list.contentY = Math.max(0, Math.min(list.music.content.scroll, Math.max(0, list.contentHeight - list.height)))
            list.restoring = false
        })
    }
    onPageKeyChanged: restore()
    onMovementEnded: music.save_scroll(contentY)
    onContentYChanged: {
        if (!restoring && visible) music.save_scroll(contentY)
        if (!restoring && moving && contentY + height > contentHeight - Theme.track * 5)
            music.more()
    }
    function activate(row) {
        music.save_scroll(contentY)
        if (row.kind === "track") { if (row.available) music.play(row.id) }
        else music.open_entity(row.kind, row.id)
    }
    Keys.onReturnPressed: if (currentIndex >= 0) activate(model[currentIndex])
    Keys.onEnterPressed: if (currentIndex >= 0) activate(model[currentIndex])
    section.property: "section"
    section.delegate: Label { required property string section; text: section; height: section ? 38 : 0; font.bold: true; color: Theme.secondary; verticalAlignment: Text.AlignVCenter }

    delegate: ItemDelegate {
        id: row
        required property var modelData
        required property int index
        objectName: "trackRow" + index
        property bool currentTrack: modelData.kind === "track" && list.viewState.currentId === String(modelData.id).split(":")[0]
        width: ListView.view.width
        height: Theme.track + (modelData.reason ? 16 : 0)
        padding: Theme.small
        Accessible.name: modelData.title + ", " + modelData.detail + (currentTrack ? ", текущий трек" : "")
        onClicked: { list.currentIndex = index; list.forceActiveFocus(); list.activate(modelData) }
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: { if (row.modelData.kind === "track" && row.modelData.albumId) trackMenu.popup() }
        }
        Menu {
            id: trackMenu
            objectName: "trackMenu"
            MenuItem { text: "Перейти к альбому"; onTriggered: list.music.open_entity("album", String(row.modelData.albumId)) }
        }
        background: Rectangle {
            color: row.currentTrack ? Theme.selected : row.hovered ? Theme.hover : "transparent"
            radius: Theme.radius / 2
            border.width: (row.ListView.isCurrentItem && list.activeFocus) ? 2 : 0
            border.color: Theme.accent
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line; opacity: 0.35 }
        }
        contentItem: RowLayout {
            spacing: Theme.gap
            Artwork { url: row.modelData.cover || ""; Layout.preferredWidth: 44; Layout.preferredHeight: 44 }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 3
                Label { text: row.modelData.title; color: row.currentTrack ? Theme.accent : Theme.text; font.bold: row.currentTrack; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
                Label { visible: Boolean(row.modelData.reason); text: row.modelData.reason || ""; color: Theme.secondary; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true; textFormat: Text.PlainText }
                EntityLinks { visible: row.modelData.kind === "track" && row.modelData.available; music: list.music; rowData: row.modelData; Layout.fillWidth: true }
                Label { visible: row.modelData.kind !== "track" || !row.modelData.available; text: (row.modelData.available ? "" : "Недоступен · ") + row.modelData.detail; color: Theme.secondary; font.pixelSize: Theme.caption; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
            }
            Label {
                visible: row.currentTrack
                text: Theme.playbackLabel(list.viewState.playbackStatus)
                color: Theme.secondary
                font.pixelSize: Theme.caption
            }
            LikeButton {
                music: list.music
                trackId: String(row.modelData.id || "")
                albumId: String(row.modelData.albumId || "")
                visible: row.modelData.kind === "track"
                Layout.preferredWidth: 36
                Layout.preferredHeight: 36
            }
            Label { visible: list.width > 520 && row.modelData.kind === "track"; text: row.modelData.available ? Theme.clock(row.modelData.duration) : "Недоступен"; color: Theme.secondary }
            ActionButton {
                objectName: "trackMenuButton"; symbol: "menu"; iconOnly: true; text: "Действия с треком"
                visible: row.modelData.kind === "track" && Boolean(row.modelData.albumId)
                onClicked: trackMenu.popup()
            }
        }
    }
    footer: Item {
        width: list.width
        height: list.viewState.more || list.viewState.pageStatus === "loading" ? 56 : 0
        ActionButton {
            anchors.centerIn: parent
            visible: list.viewState.more
            text: list.viewState.pageStatus === "loading" ? "Загружаем…" : "Показать ещё"
            enabled: list.viewState.pageStatus === "ready"
            onClicked: list.music.more()
        }
    }
}
