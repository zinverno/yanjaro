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
        height: Theme.track
        padding: Theme.small
        Accessible.name: modelData.title + ", " + modelData.detail + (currentTrack ? ", текущий трек" : "")
        onClicked: { list.currentIndex = index; list.forceActiveFocus(); list.activate(modelData) }
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
                spacing: 3
                Label { text: row.modelData.title; color: row.currentTrack ? Theme.accent : Theme.text; font.bold: row.currentTrack; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
                EntityLinks { visible: row.modelData.kind === "track" && row.modelData.available; music: list.music; rowData: row.modelData; Layout.fillWidth: true }
                Label { visible: row.modelData.kind !== "track" || !row.modelData.available; text: (row.modelData.available ? "" : "Недоступен · ") + row.modelData.detail; color: Theme.secondary; font.pixelSize: Theme.caption; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
            }
            Label {
                visible: row.currentTrack
                text: Theme.playbackLabel(list.viewState.playbackStatus)
                color: Theme.secondary
                font.pixelSize: Theme.caption
            }
            Label { visible: list.width > 520 && row.modelData.kind === "track"; text: row.modelData.available ? Theme.clock(row.modelData.duration) : "Недоступен"; color: Theme.secondary }

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
