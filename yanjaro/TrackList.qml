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
        if (!restoring && moving && contentY + height > contentHeight - Theme.track * 5)
            music.more()
    }
    Keys.onReturnPressed: if (currentIndex >= 0 && model[currentIndex].available) music.play(model[currentIndex].id)
    Keys.onEnterPressed: if (currentIndex >= 0 && model[currentIndex].available) music.play(model[currentIndex].id)
    delegate: ItemDelegate {
        id: row
        required property var modelData
        required property int index
        property bool currentTrack: list.viewState.currentId === String(modelData.id).split(":")[0]
        width: ListView.view.width
        height: Theme.track
        padding: Theme.small
        Accessible.name: modelData.title + ", " + modelData.detail + (currentTrack ? ", текущий трек" : "")
        onClicked: { list.currentIndex = index; list.forceActiveFocus() }
        onDoubleClicked: if (modelData.available) list.music.play(modelData.id)
        background: Rectangle {
            color: row.ListView.isCurrentItem ? Theme.selected : row.hovered ? Theme.hover : "transparent"
            radius: Theme.radius / 2
            border.width: row.visualFocus ? 2 : 0
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
                Label { text: (row.modelData.available ? "" : "Недоступен · ") + row.modelData.detail; color: Theme.secondary; font.pixelSize: Theme.caption; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
            }
            Label {
                visible: row.currentTrack
                text: list.viewState.loading ? "Загрузка" : list.viewState.loaded ? (list.viewState.paused ? "Пауза" : "Играет") : "Выбран"
                color: Theme.secondary
                font.pixelSize: Theme.caption
            }
            Label { visible: list.width > 520; text: row.modelData.available ? Theme.clock(row.modelData.duration) : "Недоступен"; color: Theme.secondary }
            ActionButton {
                objectName: "rowPlay" + row.index
                iconOnly: true
                symbol: "play"
                text: row.modelData.available ? "Слушать «" + row.modelData.title + "»" : "Трек недоступен"
                enabled: row.modelData.available && list.viewState.ready
                onClicked: list.music.play(row.modelData.id)
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
