pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: stations
    required property var music
    required property var viewState
    spacing: Theme.small
    readonly property real scrollPosition: grid.contentY
    property var collapsed: ({})
    property int columns: Math.max(1, Math.floor(width / 210))
    function bundles() {
        let result = []
        for (let group of music.stationGroups) {
            result.push({heading:group.title, stations:[]})
            if (!collapsed[group.title] || stationFilter.text.length > 0)
                for (let i=0; i<group.rows.length; i+=columns)
                    result.push({heading:"", stations:group.rows.slice(i, i+columns)})
        }
        return result
    }
    onVisibleChanged: if (visible) Qt.callLater(function() { grid.contentY = stations.music.content.scroll })
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: stations.height < 330 ? 58 : 90
        radius: Theme.radius
        color: Theme.selected
        RowLayout {
            anchors.fill: parent; anchors.margins: Theme.gap
            ColumnLayout {
                Layout.fillWidth: true
                Label { text: "Моя волна"; font.pixelSize: 22; font.bold: true }
                Label { visible: stations.height >= 330; text: stations.viewState.stationId === "user:onyourwave" ? Theme.playbackLabel(stations.viewState.playbackStatus) : "Персональная станция Яндекс Музыки"; color: Theme.secondary; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
            ActionButton { text: "Слушать"; symbol: "play"; primary: true; enabled: stations.viewState.signedIn && stations.viewState.ready; onClicked: stations.music.start_wave("user:onyourwave") }
        }
    }
    TextField {
        id: stationFilter
        objectName: "stationFilter"
        Layout.fillWidth: true
        implicitHeight: Theme.button
        placeholderText: "Найти станцию"
        Accessible.name: "Найти станцию по всему каталогу"
        maximumLength: 200
        onTextChanged: stations.music.filter_stations(text)
    }
    ListView {
        id: grid
        objectName: "stationsGrid"
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true; reuseItems: true
        model: stations.bundles()
        onMovementEnded: stations.music.save_scroll(contentY)
        ScrollBar.vertical: ScrollBar {}
        delegate: Item {
            id: bundle
            required property var modelData
            required property int index
            width: grid.width
            height: modelData.heading ? 42 : stations.height < 330 ? 116 : 148
            ActionButton {
                visible: bundle.modelData.heading.length > 0
                width: parent.width; height: 40
                text: bundle.modelData.heading
                onClicked: { let next = Object.assign({}, stations.collapsed); next[bundle.modelData.heading] = !next[bundle.modelData.heading]; stations.collapsed = next }
                Accessible.description: stations.collapsed[bundle.modelData.heading] ? "Развернуть группу" : "Свернуть группу"
            }
            Row {
                spacing: Theme.small
                Repeater {
                    model: bundle.modelData.stations
                    ItemDelegate {
                        id: card
                        required property var modelData
                        property bool activeStation: stations.viewState.stationId === modelData.id
                        width: (grid.width - Theme.small * (stations.columns - 1)) / stations.columns
                        height: bundle.height - Theme.small
                        padding: Theme.small
                        Accessible.name: modelData.title + (activeStation ? ", " + Theme.playbackLabel(stations.viewState.playbackStatus) : ", запустить станцию")
                        onClicked: stations.music.start_wave(modelData.id)
                        background: Rectangle { radius: Theme.radius; color: card.hovered ? Theme.hover : Theme.surface; border.width: card.visualFocus ? 2 : card.activeStation ? 1 : 0; border.color: Theme.accent }
                        contentItem: ColumnLayout {
                            spacing: 4
                            RowLayout {
                                Artwork { url: card.modelData.cover || ""; fallback: card.modelData.fallback || "music"; Layout.preferredWidth: 42; Layout.preferredHeight: 42 }
                                Item { Layout.fillWidth: true }
                                ActionButton {
                                    symbol: "menu"; iconOnly: true; text: "Действия станции «" + card.modelData.title + "»"
                                    onClicked: stationMenu.open()
                                    Menu {
                                        id: stationMenu
                                        MenuItem { text: card.modelData.pinned ? "Открепить" : "Закрепить на устройстве"; onTriggered: stations.music.station_action(card.modelData.id, "pins") }
                                        MenuItem { text: card.modelData.hiddenTop ? "Вернуть в подборку сверху" : "Не показывать в подборке сверху"; onTriggered: stations.music.station_action(card.modelData.id, "hidden") }
                                    }
                                }
                            }
                            Label { text: card.modelData.title; textFormat: Text.PlainText; font.bold: true; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; Layout.fillWidth: true }
                            Label { visible: card.activeStation || card.modelData.pinned; text: card.activeStation ? Theme.playbackLabel(stations.viewState.playbackStatus) : "Закреплена"; color: Theme.accent; font.pixelSize: Theme.caption }
                        }
                    }
                }
            }
        }
        Label { anchors.centerIn: parent; visible: grid.count === 0 && stations.viewState.pageStatus === "ready"; text: "Станции не найдены"; color: Theme.secondary }
    }
}
