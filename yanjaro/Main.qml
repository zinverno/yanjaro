pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1040
    height: 730
    minimumWidth: 760
    minimumHeight: 570
    visible: true
    title: "Yanjaro Music"
    color: "#16191c"
    palette.window: "#16191c"
    palette.windowText: "#f0f2f3"
    palette.base: "#20252a"
    palette.alternateBase: "#272e34"
    palette.text: "#f0f2f3"
    palette.button: "#303840"
    palette.buttonText: "#f0f2f3"
    palette.highlight: "#d9eb72"
    palette.highlightedText: "#151916"
    required property var music
    property var s: window.music.state
    font.pixelSize: 14

    function clock(seconds) {
        let n = Math.max(0, Math.floor(seconds || 0))
        return Math.floor(n / 60) + ":" + (n % 60).toString().padStart(2, "0")
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            Label { text: "YANJARO"; font.pixelSize: 23; font.bold: true; color: "#d9eb72" }
            Label { text: "Музыка на вашем компьютере"; color: "#aab4bc"; Layout.fillWidth: true }
            Button {
                objectName: "loginButton"
                text: window.s.signedIn ? "Выйти" : "Войти через браузер"
                enabled: !window.s.busy
                onClicked: window.s.signedIn ? window.music.logout() : window.music.login()
            }
        }

        Frame {
            visible: !window.s.signedIn
            Layout.fillWidth: true
            ColumnLayout {
                width: parent.width
                spacing: 10
                Label {
                    text: "Ваша библиотека — после входа"
                    font.pixelSize: 22
                    font.bold: true
                }
                Label {
                    text: "Подтвердите доступ на странице Яндекса. Токен хранится только до выхода из приложения."
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Label {
                    visible: window.s.code.length > 0
                    text: "Код: " + window.s.code
                    font.pixelSize: 26
                    font.bold: true
                    color: "#d9eb72"
                    Accessible.name: "Код подтверждения " + window.s.code
                }
                Label { visible: window.s.code.length > 0; text: window.s.loginUrl; textFormat: Text.PlainText }
                RowLayout {
                    visible: window.s.busy
                    Button { text: "Открыть браузер ещё раз"; visible: window.s.code.length > 0; onClicked: window.music.open_browser() }
                    Button { text: "Отменить вход"; onClicked: window.music.cancel_login() }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            enabled: window.s.signedIn && !window.s.busy
            Button { text: "Мне нравится"; onClicked: window.music.show("likes") }
            TextField {
                id: searchField
                objectName: "searchField"
                Layout.fillWidth: true
                placeholderText: "Название песни или исполнитель"
                maximumLength: 300
                Accessible.name: "Поиск песни"
                onAccepted: window.music.search(text)
            }
            Button { text: "Найти"; enabled: searchField.text.trim().length > 0; onClicked: window.music.search(searchField.text) }
        }

        RowLayout {
            Layout.fillWidth: true
            enabled: window.s.signedIn && !window.s.busy
            Button { text: "Станции"; onClicked: window.music.show("stations") }
            Button { text: "Моя волна"; onClicked: window.music.start_wave("user:onyourwave") }
            Button { text: "Следующая партия →"; enabled: window.s.waveActive; onClicked: window.music.next_wave() }
            Button { text: "История"; onClicked: window.music.show("history") }
            Item { Layout.fillWidth: true }
        }

        RowLayout {
            Label { text: window.s.heading; font.pixelSize: 25; font.bold: true; Layout.fillWidth: true }
            BusyIndicator { running: window.s.busy; visible: running; implicitWidth: 26; implicitHeight: 26 }
        }

        ListView {
            id: tracks
            objectName: "tracksList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: window.s.rows
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                id: row
                required property var modelData
                required property int index
                width: ListView.view.width
                height: 64
                enabled: !window.s.busy && row.modelData.available
                Accessible.name: row.modelData.title + ", " + row.modelData.detail
                onClicked: window.music.play(row.modelData.id)
                contentItem: RowLayout {
                    Label { text: (row.index + 1).toString().padStart(2, "0"); color: "#aab4bc"; Layout.preferredWidth: 32 }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Label { text: row.modelData.title; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; font.bold: true }
                        Label { text: row.modelData.detail; textFormat: Text.PlainText; elide: Text.ElideRight; color: "#aab4bc"; Layout.fillWidth: true }
                    }
                    Label { text: row.modelData.kind === "station" ? "Запустить" : (row.modelData.available ? window.clock(row.modelData.duration) : "Недоступен") }
                    Label { text: "▶"; color: "#d9eb72" }
                }
            }
            Label {
                anchors.centerIn: parent
                visible: !window.s.busy && window.s.rows.length === 0
                text: window.s.signedIn ? "Здесь пока нет треков" : "Войдите в аккаунт, чтобы начать"
                color: "#aab4bc"
            }
        }

        Button { text: "Показать ещё"; visible: window.s.more; enabled: !window.s.busy; Layout.alignment: Qt.AlignHCenter; onClicked: window.music.more() }
        Label {
            text: window.s.message
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            color: "#d1d9df"
            Accessible.role: Accessible.StaticText
        }
        Label {
            visible: window.s.signedIn && window.s.view === "history"
            text: window.s.playReport
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            color: "#aab4bc"
        }

        Rectangle { color: "#394149"; Layout.fillWidth: true; implicitHeight: 1 }
        Label { text: window.s.current; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; font.bold: true }
        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "pauseButton"
                text: window.s.paused ? "Продолжить" : "Пауза"
                enabled: window.s.loaded
                onClicked: window.music.pause()
            }
            Label { text: window.clock(window.s.position); Layout.preferredWidth: 42 }
            Slider {
                id: seek
                objectName: "seekSlider"
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, window.s.duration)
                enabled: window.s.loaded && window.s.seekable
                Accessible.name: "Позиция воспроизведения"
                Binding { target: seek; property: "value"; value: window.s.position; when: !seek.pressed }
                onPressedChanged: if (!pressed) window.music.seek(value)
                Keys.onLeftPressed: window.music.seek(Math.max(0, window.s.position - 5))
                Keys.onRightPressed: window.music.seek(Math.min(window.s.duration, window.s.position + 5))
            }
            Label { text: window.clock(window.s.duration); Layout.preferredWidth: 42 }
            Label { text: window.s.buffering ? "Буферизация…" : ""; color: "#aab4bc" }
        }
    }
}
