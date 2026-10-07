pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: stations
    required property var music
    required property var viewState
    spacing: height < 330 ? Theme.small : Theme.gap
    readonly property real scrollPosition: grid.contentY
    onVisibleChanged: if (visible) Qt.callLater(function() { grid.contentY = stations.music.content.scroll })
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: stations.height < 330 ? 56 : 112
        radius: Theme.radius
        color: Theme.selected
        RowLayout {
            anchors.fill: parent
            anchors.margins: stations.height < 330 ? Theme.small : Theme.margin
            ColumnLayout {
                Layout.fillWidth: true
                Label { text: "Моя волна"; font.pixelSize: 22; font.bold: true }
                Label { visible: stations.height >= 330; text: stations.viewState.stationId === "user:onyourwave" ? "Текущий источник музыки" : "Персональная станция Яндекс Музыки"; color: Theme.secondary; wrapMode: Text.WordWrap; Layout.fillWidth: true }
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
        Accessible.name: "Найти станцию в каталоге"
        maximumLength: 200
    }
    GridView {
        id: grid
        objectName: "stationsGrid"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        cellWidth: width / Math.max(1, Math.floor(width / 210))
        cellHeight: stations.height < 330 ? 104 : 136
        model: stations.music.content.rows.filter(r => r.title.toLocaleLowerCase().includes(stationFilter.text.toLocaleLowerCase()))
        onMovementEnded: stations.music.save_scroll(contentY)
        ScrollBar.vertical: ScrollBar {}
        delegate: ItemDelegate {
            id: card
            required property var modelData
            required property int index
            property bool activeStation: stations.viewState.stationId === modelData.id
            width: grid.cellWidth - Theme.small
            height: grid.cellHeight - Theme.small
            enabled: stations.viewState.signedIn && stations.viewState.ready
            padding: stations.height < 330 ? 12 : Theme.gap
            Accessible.name: modelData.title + (activeStation ? ", активная станция" : ", запустить станцию")
            onClicked: stations.music.start_wave(modelData.id)
            background: Rectangle {
                radius: Theme.radius
                color: card.hovered ? Theme.hover : Theme.surface
                border.width: card.visualFocus ? 2 : card.activeStation ? 1 : 0
                border.color: Theme.accent
            }
            contentItem: ColumnLayout {
                spacing: Theme.small
                RowLayout {
                    Rectangle { implicitWidth: stations.height < 330 ? 24 : 30; implicitHeight: implicitWidth; color: Theme.accent; radius: Theme.radius; Image { anchors.centerIn: parent; width: 18; height: 18; source: "icons/radio.svg" } }
                    Item { Layout.fillWidth: true }
                    Label { text: card.activeStation ? "Активна" : ""; color: Theme.accent; font.pixelSize: Theme.caption }
                }
                Label { text: card.modelData.title; textFormat: Text.PlainText; font.bold: true; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight; Layout.fillWidth: true }
            }
        }
        Label { anchors.centerIn: parent; visible: grid.count === 0 && stations.viewState.pageStatus === "ready"; text: "Станции не найдены"; color: Theme.secondary }
    }
}
