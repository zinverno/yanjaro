pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: experiment
    required property var music
    required property var viewState
    Label { text: "Конечный микс до 30 песен. Правила отбора и порядок Yanjaro; каталог и звук — Яндекс. Превосходство над «Моей волной» не доказано."; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: Theme.secondary; font.pixelSize: Theme.caption }
    RowLayout {
        Layout.fillWidth: true
        ActionButton { text: "Собрать новый"; primary: true; enabled: experiment.viewState.pageStatus !== "loading"; onClicked: experiment.music.build_mix() }
        ActionButton { text: "Слушать"; symbol: "play"; enabled: experiment.music.content.rows.length > 0; onClicked: experiment.music.play_page() }
        Label { text: experiment.viewState.loadedCount + " треков"; color: Theme.secondary }
        Item { Layout.fillWidth: true }
    }
    RowLayout {
        Layout.fillWidth: true
        Label { text: "Знакомое"; color: Theme.secondary }
        Slider {
            id: balance
            from: 0; to: 1; stepSize: .1
            Layout.preferredWidth: 200
            value: experiment.viewState.experimentBalance
            Accessible.name: "Баланс знакомой и новой музыки"
            onPressedChanged: if (!pressed) experiment.music.experiment_balance(value)
            Keys.onLeftPressed: experiment.music.experiment_balance(Math.max(0,value-.1))
            Keys.onRightPressed: experiment.music.experiment_balance(Math.min(1,value+.1))
        }
        Label { text: "Новое"; color: Theme.secondary }
        Item { Layout.fillWidth: true }
    }
    Flow {
        Layout.fillWidth: true
        spacing: Theme.small
        ActionButton { text: "Добавить текущий трек как исходный"; enabled: experiment.viewState.currentId.length > 0; onClicked: experiment.music.seed_experiment() }
        Label { text: "Исходных: " + experiment.viewState.experimentSeeds; height: Theme.button; verticalAlignment: Text.AlignVCenter; color: Theme.secondary }
    }
    Flow {
        Layout.fillWidth: true
        spacing: Theme.small
        ActionButton { text: "Больше такого"; selected: experiment.viewState.experimentRating === 1; enabled: experiment.viewState.currentId.length > 0; onClicked: experiment.music.rate_experiment(1) }
        ActionButton { text: "Меньше такого"; selected: experiment.viewState.experimentRating === -1; enabled: experiment.viewState.currentId.length > 0; onClicked: experiment.music.rate_experiment(-1) }
        ActionButton { text: "Не предлагать"; selected: experiment.viewState.experimentRating === -2; enabled: experiment.viewState.currentId.length > 0; onClicked: experiment.music.rate_experiment(-2) }
        ActionButton { text: "Снять оценку"; enabled: experiment.viewState.experimentRating !== 0; onClicked: experiment.music.rate_experiment(0) }
    }
    Label { text: experiment.viewState.experimentMessage; wrapMode: Text.WordWrap; Layout.fillWidth: true; color: Theme.secondary; textFormat: Text.PlainText; font.pixelSize: Theme.caption }
}
