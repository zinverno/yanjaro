pragma Singleton
import QtQuick
QtObject {
    readonly property color background: "#171a1c"
    readonly property color sidebar: "#1d2124"
    readonly property color surface: "#24292d"
    readonly property color hover: "#30373b"
    readonly property color selected: "#343d2b"
    readonly property color line: "#394045"
    readonly property color text: "#f0f2ef"
    readonly property color secondary: "#afb7b9"
    readonly property color accent: "#c3d681"
    readonly property color accentText: "#20271a"
    readonly property color error: "#f0b3a8"
    readonly property int small: 8
    readonly property int gap: 16
    readonly property int margin: 24
    readonly property int radius: 8
    readonly property int button: 38
    readonly property int track: 60
    readonly property int sidebarWidth: 204
    readonly property int playerHeight: 100
    readonly property int body: 14
    readonly property int caption: 12
    readonly property int title: 28
    function playbackLabel(status) {
        return ({playing: "Играет", paused: "Пауза", loading: "Загрузка", buffering: "Буферизация", error: "Ошибка", stopped: "Остановлен"})[status] || ""
    }
    function clock(seconds) {
        let n = Math.max(0, Math.floor(seconds || 0))
        return Math.floor(n / 60) + ":" + (n % 60).toString().padStart(2, "0")
    }
}
