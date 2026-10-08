pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    id: bar
    required property var music
    required property var viewState
    signal showQueue()
    objectName: "playerBar"
    implicitHeight: Theme.playerHeight
    color: Theme.sidebar
    Rectangle { width: parent.width; height: 1; color: Theme.line }
    RowLayout {
        id: metadata
        objectName: "playerMetadata"
        anchors.left: parent.left
        anchors.leftMargin: Theme.gap
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(360, center.x - Theme.gap * 2)
        spacing: Theme.small
        Artwork { url: bar.viewState.cover; visible: metadata.width > 160; Layout.preferredWidth: 48; Layout.preferredHeight: 48 }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            Label { text: bar.viewState.current; font.bold: true; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; ToolTip.visible: titleHover.hovered; ToolTip.text: text; HoverHandler { id: titleHover } }
            EntityLinks { music: bar.music; rowData: bar.viewState.currentRow; Layout.fillWidth: true }
            Label { text: bar.viewState.source; visible: text.length > 0; color: Theme.accent; font.pixelSize: Theme.caption; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
        }
    }
    ColumnLayout {
        id: center
        objectName: "playerCenter"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(560, bar.width - 2 * (volumeControls.width + Theme.gap * 2))
        spacing: 0
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: bar.width < 900 ? 4 : Theme.small
            ActionButton { objectName: "shuffleButton"; symbol: "shuffle"; iconOnly: true; selected: bar.viewState.shuffle; text: bar.viewState.finiteQueue ? (bar.viewState.shuffle ? "Выключить перемешивание" : "Перемешать оставшиеся треки") : "Перемешивание доступно для конечной очереди"; enabled: bar.viewState.finiteQueue; onClicked: bar.music.set_shuffle(!bar.viewState.shuffle) }
            ActionButton { objectName: "previousButton"; symbol: "previous"; iconOnly: true; text: "Предыдущий трек"; enabled: bar.viewState.canPrevious; onClicked: bar.music.previous_track() }
            ActionButton {
                objectName: "pauseButton"
                implicitWidth: 46; implicitHeight: 46
                symbol: bar.viewState.playbackStatus === "playing" || bar.viewState.playbackStatus === "buffering" || (bar.viewState.loading && !bar.viewState.desiredPaused) ? "pause" : "play"
                iconOnly: true
                primary: true
                text: bar.viewState.loading ? (bar.viewState.desiredPaused ? "Продолжить после загрузки" : "Пауза после загрузки") : symbol === "pause" ? "Пауза" : "Продолжить"
                enabled: bar.viewState.currentId.length > 0 && bar.viewState.ready
                onClicked: bar.music.pause()
            }
            ActionButton { objectName: "nextButton"; symbol: "next"; iconOnly: true; text: "Следующий трек"; enabled: bar.viewState.canNext; onClicked: bar.music.next_track() }
            ActionButton { objectName: "repeatButton"; symbol: bar.viewState.repeatMode === "Track" ? "repeat-one" : "repeat"; iconOnly: true; selected: bar.viewState.repeatMode !== "None"; text: !bar.viewState.finiteQueue ? "Повтор доступен для конечной очереди" : "Повтор: " + ({None: "выключен", Playlist: "вся очередь", Track: "один трек"})[bar.viewState.repeatMode]; enabled: bar.viewState.finiteQueue; onClicked: bar.music.cycle_repeat() }
        }
        RowLayout {
            spacing: Theme.small
            Label { text: Theme.clock(bar.viewState.position); color: Theme.secondary; font.pixelSize: Theme.caption; Layout.preferredWidth: 36 }
            Slider {
                id: seek
                objectName: "seekSlider"
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, bar.viewState.duration)
                enabled: bar.viewState.loaded && bar.viewState.seekable
                Accessible.name: "Позиция воспроизведения"
                Binding { target: seek; property: "value"; value: bar.viewState.position; when: !seek.pressed }
                onPressedChanged: if (!pressed) bar.music.seek(value)
                Keys.onLeftPressed: bar.music.seek(Math.max(0, bar.viewState.position - 5))
                Keys.onRightPressed: bar.music.seek(Math.min(bar.viewState.duration, bar.viewState.position + 5))
            }
            Label { text: Theme.clock(bar.viewState.duration); color: Theme.secondary; font.pixelSize: Theme.caption; Layout.preferredWidth: 36 }
        }
    }
    BusyIndicator { anchors.bottom: parent.bottom; anchors.bottomMargin: 2; anchors.horizontalCenter: parent.horizontalCenter; running: bar.viewState.loading || bar.viewState.buffering; visible: running; width: 16; height: 16 }
    RowLayout {
        id: volumeControls
        objectName: "volumeControls"
        anchors.right: parent.right
        anchors.rightMargin: Theme.gap
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        ActionButton { objectName: "muteButton"; symbol: bar.viewState.muted ? "muted" : "volume"; iconOnly: true; text: bar.viewState.muted ? "Включить звук" : "Выключить звук"; enabled: bar.viewState.ready; onClicked: bar.music.mute() }
        Slider {
            id: volume
            objectName: "volumeSlider"
            Layout.preferredWidth: bar.width < 1100 ? 64 : 100
            from: 0; to: 100; stepSize: 1
            enabled: bar.viewState.ready
            Accessible.name: "Громкость"
            Binding { target: volume; property: "value"; value: bar.viewState.volume; when: !volume.pressed }
            onMoved: bar.music.volume(value)
            ToolTip.visible: hovered || pressed
            ToolTip.text: Math.round(value) + "%"
        }
        ActionButton { objectName: "queueButton"; symbol: "queue"; iconOnly: true; text: "Очередь воспроизведения"; onClicked: bar.showQueue() }
    }
}
