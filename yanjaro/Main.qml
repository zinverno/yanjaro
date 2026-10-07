pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    required property var music
    property var s: music.state
    width: 1180
    height: 760
    minimumWidth: 680
    minimumHeight: 440
    visible: true
    title: "Yanjaro Music"
    color: Theme.background
    font.pixelSize: Theme.body
    palette.window: Theme.background
    palette.windowText: Theme.text
    palette.base: Theme.surface
    palette.text: Theme.text
    palette.button: Theme.surface
    palette.buttonText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.accentText
    palette.placeholderText: Theme.secondary

    function navigate(view) {
        if (tracks.visible) music.save_scroll(tracks.contentY)
        else if (stationPage.visible) music.save_scroll(stationPage.scrollPosition)
        music.show(view)
    }
    Shortcut { sequence: "Ctrl+F"; onActivated: { search.forceActiveFocus(); search.selectAll() } }
    Shortcut { sequence: "Ctrl+L"; onActivated: { search.forceActiveFocus(); search.selectAll() } }
    Shortcut {
        sequence: "Space"
        enabled: window.s.loaded && !(window.activeFocusItem instanceof TextInput) && !(window.activeFocusItem instanceof TextEdit) && !(window.activeFocusItem instanceof AbstractButton)
        onActivated: window.music.pause()
    }

    RowLayout {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: errors.top
        spacing: 0
        Rectangle {
            Layout.preferredWidth: window.width < 900 ? 180 : Theme.sidebarWidth
            Layout.fillHeight: true
            color: Theme.sidebar
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.gap
                spacing: Theme.small
                RowLayout {
                    Layout.topMargin: Theme.small
                    Layout.bottomMargin: Theme.margin
                    spacing: Theme.small
                    Image { source: "icons/yanjaro.svg"; sourceSize.width: 32; sourceSize.height: 32 }
                    Label { text: "Yanjaro"; font.pixelSize: 23; font.bold: true }
                }
                Label { text: "ВАША МУЗЫКА"; font.pixelSize: 10; font.letterSpacing: 1.5; color: Theme.secondary; Layout.leftMargin: 12; Layout.bottomMargin: Theme.small }
                ActionButton { objectName: "navLikes"; text: "Мне нравится"; symbol: "favorite"; selected: window.s.view === "likes"; Layout.fillWidth: true; onClicked: window.navigate("likes") }
                ActionButton { objectName: "navStations"; text: "Станции"; symbol: "radio"; selected: window.s.view === "stations"; Layout.fillWidth: true; onClicked: window.navigate("stations") }
                ActionButton { visible: window.s.view === "search" || window.s.query.length > 0; text: "Результаты поиска"; symbol: "search"; selected: window.s.view === "search"; Layout.fillWidth: true; onClicked: window.navigate("search") }
                Item { Layout.fillHeight: true }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.line }
                ActionButton {
                    objectName: "loginButton"
                    text: window.s.signedIn ? "Аккаунт" : "Войти"
                    symbol: "account"
                    Layout.fillWidth: true
                    enabled: !window.s.authBusy
                    onClicked: window.s.signedIn ? profile.open() : window.music.login()
                    Menu {
                        id: profile
                        y: -height
                        MenuItem { text: "О приложении"; onTriggered: about.open() }
                        MenuItem { text: "Выйти из аккаунта"; onTriggered: window.music.logout() }
                    }
                }
                Label { text: "Неофициальный клиент"; color: Theme.secondary; font.pixelSize: 11; Layout.leftMargin: 12 }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: window.width < 900 || window.height < 600 ? Theme.gap : Theme.margin
            spacing: window.height < 600 ? Theme.small : Theme.gap
            RowLayout {
                Layout.fillWidth: true
                TextField {
                    id: search
                    objectName: "searchField"
                    Layout.fillWidth: true
                    Layout.maximumWidth: 720
                    implicitHeight: 42
                    placeholderText: "Поиск в Яндекс Музыке"
                    Accessible.name: "Поиск в Яндекс Музыке"
                    maximumLength: 300
                    selectByMouse: true
                    onAccepted: { if (tracks.visible) window.music.save_scroll(tracks.contentY); window.music.search(text) }
                }
                ActionButton { text: "Найти"; symbol: "search"; onClicked: window.music.search(search.text) }
                Item { Layout.fillWidth: true }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.small
                Label { text: window.s.heading; font.pixelSize: Theme.title; font.bold: true; Layout.fillWidth: true }
                Label { visible: window.s.view === "likes" && window.s.total >= 0; text: window.s.total + " треков"; color: Theme.secondary }
            }
            RowLayout {
                visible: window.s.signedIn && window.s.view === "likes" && window.s.total > 0
                Layout.fillWidth: true
                ActionButton { text: "Слушать"; symbol: "play"; primary: true; enabled: window.s.ready; onClicked: window.music.play_collection(false) }
                ActionButton { text: "Перемешать"; symbol: "shuffle"; enabled: window.s.ready; onClicked: window.music.play_collection(true) }
                Item { Layout.fillWidth: true }
                Label { visible: window.width >= 900; text: "Загружено " + window.s.loadedCount + " из " + window.s.total; color: Theme.secondary; font.pixelSize: Theme.caption }
            }
            ColumnLayout {
                visible: !window.s.signedIn
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Theme.gap
                Item { Layout.fillHeight: true }
                Label { text: "Вся ваша музыка — после входа"; font.pixelSize: 22; font.bold: true; wrapMode: Text.WordWrap; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
                Label { text: "Подтвердите доступ в браузере на странице Яндекса."; color: Theme.secondary; wrapMode: Text.WordWrap; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
                ActionButton { text: window.s.authBusy ? "Ожидаем подтверждения…" : "Войти через браузер"; symbol: "account"; primary: true; enabled: !window.s.authBusy; Layout.alignment: Qt.AlignHCenter; onClicked: window.music.login() }
                Label { visible: window.s.code.length > 0; text: window.s.code; font.pixelSize: 32; font.bold: true; Layout.alignment: Qt.AlignHCenter; Accessible.name: "Код подтверждения " + window.s.code }
                Label { visible: window.s.code.length > 0; text: window.s.loginUrl; textFormat: Text.PlainText; color: Theme.secondary; wrapMode: Text.WordWrap; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
                RowLayout {
                    visible: window.s.authBusy
                    Layout.alignment: Qt.AlignHCenter
                    ActionButton { text: "Открыть браузер"; visible: window.s.code.length > 0; onClicked: window.music.open_browser() }
                    ActionButton { text: "Отменить"; onClicked: window.music.cancel_login() }
                }
                Label { visible: window.s.authError.length > 0; text: window.s.authError; textFormat: Text.PlainText; color: Theme.error; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Item { Layout.fillHeight: true }
            }
            RowLayout {
                visible: window.s.signedIn && window.s.pageError.length > 0
                Layout.fillWidth: true
                Label { text: "Не удалось загрузить раздел. " + window.s.pageError; textFormat: Text.PlainText; color: Theme.error; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                ActionButton { text: "Повторить"; symbol: "retry"; onClicked: window.music.retry_page() }
            }
            RowLayout {
                visible: window.s.signedIn && window.s.pageStatus === "loading"
                BusyIndicator { running: parent.visible; implicitWidth: 24; implicitHeight: 24 }
                Label { text: window.s.view === "search" ? "Ищем…" : "Загружаем…"; color: Theme.secondary }
            }
            TrackList {
                id: tracks
                music: window.music
                viewState: window.s
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: window.s.signedIn && window.s.view !== "stations"
                Label {
                    anchors.centerIn: parent
                    visible: tracks.count === 0 && window.s.pageStatus !== "loading" && !window.s.pageError
                    text: window.s.view === "search" ? (window.s.query ? "Ничего не найдено" : "Введите название песни или исполнителя") : "Здесь пока нет треков"
                    color: Theme.secondary
                }
            }
            Stations { id: stationPage; music: window.music; viewState: window.s; Layout.fillWidth: true; Layout.fillHeight: true; visible: window.s.signedIn && window.s.view === "stations" }
        }
    }
    ColumnLayout {
        id: errors
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: player.top
        spacing: 0
        RowLayout {
            visible: window.s.playerError.length > 0
            Layout.fillWidth: true
            Layout.margins: Theme.small
            Label { text: "Ошибка воспроизведения: " + window.s.playerError; textFormat: Text.PlainText; color: Theme.error; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            ActionButton { text: "Повторить"; symbol: "retry"; enabled: window.s.currentId.length > 0 && window.s.ready; onClicked: window.music.retry_play() }
        }
        RowLayout {
            visible: window.s.stationError.length > 0
            Layout.fillWidth: true
            Layout.margins: Theme.small
            Label { text: window.s.stationError; textFormat: Text.PlainText; color: Theme.error; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            ActionButton { text: "Повторить"; symbol: "retry"; enabled: !window.s.refilling; onClicked: window.music.retry_station() }
        }
    }
    PlayerBar { id: player; music: window.music; viewState: window.s; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: Theme.playerHeight; onShowQueue: queue.opened ? queue.close() : queue.open() }
    Drawer {
        id: queue
        objectName: "queuePanel"
        edge: Qt.RightEdge
        width: 340
        height: window.height - player.height
        modal: false
        dim: false
        background: Rectangle { color: Theme.sidebar; border.color: Theme.line }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.gap
            RowLayout {
                Label { text: "Очередь"; font.pixelSize: 22; font.bold: true; Layout.fillWidth: true }
                ActionButton { text: "Закрыть очередь"; symbol: "close"; iconOnly: true; onClicked: queue.close() }
            }
            Label { text: window.s.source || "Музыка ещё не выбрана"; textFormat: Text.PlainText; color: Theme.secondary; elide: Text.ElideRight; Layout.fillWidth: true }
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                reuseItems: true
                model: window.music.queueRows
                ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate {
                    id: queued
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    height: Theme.track
                    enabled: modelData.available && modelData.queueIndex !== -1
                    onClicked: window.music.jump_queue(modelData.queueIndex)
                    contentItem: ColumnLayout {
                        Label { text: (queued.modelData.isCurrent ? (window.s.loading ? "Загрузка: " : "Сейчас: ") : "") + queued.modelData.title; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; color: queued.modelData.isCurrent ? Theme.accent : Theme.text }
                        Label { text: queued.modelData.artist || queued.modelData.detail || ""; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; color: Theme.secondary; font.pixelSize: Theme.caption }
                    }
                }
            }
        }
    }
    Dialog {
        id: about
        title: "О Yanjaro Music"
        anchors.centerIn: parent
        width: 470
        modal: true
        standardButtons: Dialog.Ok
        Label { width: parent.width; text: "Неофициальный клиент Яндекс Музыки.\nGPL-3.0-or-later, без гарантий.\n\nТокен хранится только в памяти до выхода.\nИстория временно скрыта: новые прослушивания в ней не подтверждены.\n\nИконки: GNOME Project / Adwaita (LGPL-3.0)."; wrapMode: Text.WordWrap }
    }
}
