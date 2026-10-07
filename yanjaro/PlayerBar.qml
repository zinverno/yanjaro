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
        anchors.fill: parent
        anchors.margins: Theme.gap
        spacing: Theme.margin
        RowLayout {
            Layout.preferredWidth: Math.min(320, bar.width * 0.28)
            spacing: Theme.small
            Artwork { url: bar.viewState.cover; Layout.preferredWidth: 52; Layout.preferredHeight: 52 }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Label { text: bar.viewState.current; font.bold: true; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
                Label { text: bar.viewState.artist || "Выберите музыку"; color: Theme.secondary; font.pixelSize: Theme.caption; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
                Label { text: bar.viewState.source; visible: text.length > 0; color: Theme.accent; font.pixelSize: Theme.caption; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.maximumWidth: 620
            spacing: 0
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.small
                ActionButton { objectName: "previousButton"; symbol: "previous"; iconOnly: true; text: "Предыдущий трек"; enabled: bar.viewState.canPrevious; onClicked: bar.music.previous_track() }
                ActionButton {
                    objectName: "pauseButton"
                    symbol: bar.viewState.loaded && !bar.viewState.paused ? "pause" : "play"
                    iconOnly: true
                    primary: true
                    text: bar.viewState.loading ? "Загрузка трека" : bar.viewState.loaded && !bar.viewState.paused ? "Пауза" : "Продолжить"
                    enabled: bar.viewState.loaded && !bar.viewState.loading
                    onClicked: bar.music.pause()
                }
                ActionButton { objectName: "nextButton"; symbol: "next"; iconOnly: true; text: "Следующий трек"; enabled: bar.viewState.canNext; onClicked: bar.music.next_track() }
                BusyIndicator { running: bar.viewState.loading || bar.viewState.buffering; visible: running; implicitWidth: 24; implicitHeight: 24 }
            }
            RowLayout {
                spacing: Theme.small
                Label { text: Theme.clock(bar.viewState.position); color: Theme.secondary; font.pixelSize: Theme.caption; Layout.preferredWidth: 38 }
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
                Label { text: Theme.clock(bar.viewState.duration); color: Theme.secondary; font.pixelSize: Theme.caption; Layout.preferredWidth: 38 }
            }
        }
        Item { Layout.fillWidth: true; visible: bar.width > 1400 }
        RowLayout {
            spacing: 4
            ActionButton { objectName: "muteButton"; symbol: bar.viewState.muted ? "muted" : "volume"; iconOnly: true; text: bar.viewState.muted ? "Включить звук" : "Выключить звук"; enabled: bar.viewState.ready; onClicked: bar.music.mute() }
            Slider {
                id: volume
                objectName: "volumeSlider"
                Layout.preferredWidth: bar.width < 1100 ? 76 : 112
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
}
