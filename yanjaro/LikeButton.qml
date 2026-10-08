import QtQuick
import QtQuick.Controls

ActionButton {
    id: heart
    required property var music
    required property string trackId
    property string albumId: ""
    property string key: trackId.split(":")[0]
    property var snapshot: music.likesState
    property bool liked: snapshot.liked[key] === true
    property bool pending: snapshot.pending[key] === true
    objectName: "likeButton"
    implicitWidth: 36
    implicitHeight: 36
    iconOnly: true
    symbol: liked ? "heart-filled" : "heart"
    icon.color: liked ? Theme.accent : Theme.secondary
    icon.width: 22
    icon.height: 22
    enabled: trackId.length > 0 && snapshot.ready && !pending
    text: pending ? "Обновляем отметку «Мне нравится»" :
          !snapshot.ready ? "Загружаем любимые треки" :
          liked ? "Убрать из «Мне нравится»" : "Добавить в «Мне нравится»"
    onClicked: music.toggle_like(trackId, albumId)
    BusyIndicator { anchors.centerIn: parent; width: 24; height: 24; running: heart.pending; visible: running }
}
