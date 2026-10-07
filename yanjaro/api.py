"""Blocking API adapter. Only the background worker may call this module.

SDK models (which retain the authenticated client) never cross into QML.
"""

import logging
import time
from dataclasses import dataclass, field
from threading import Event
from urllib.parse import urlsplit

from yandex_music import Client, StationTracksResult
from yandex_music.exceptions import DeviceAuthError, NetworkError, UnauthorizedError
from yandex_music.utils.request import Request


class ApiError(Exception):
    """A fixed, safe message, never a server response or a URL."""


def private_logging():
    # The SDK debug decorator logs whole responses, including OAuth tokens.
    logging.disable(logging.CRITICAL)


def safe_error(exc):
    if isinstance(exc, ApiError):
        return str(exc)
    if isinstance(exc, UnauthorizedError):
        return "Доступ отклонён. Выйдите и войдите заново."
    if isinstance(exc, NetworkError):
        return "Сеть недоступна или истёк таймаут. Повторите действие."
    if isinstance(exc, DeviceAuthError):
        return "Яндекс не подтвердил вход. Повторите вход через браузер."
    return "Операция не выполнена. Ответ сервиса не поддерживается или доступ ограничен."


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    duration: float
    available: bool
    album_id: str = ""

    def row(self, detail=""):
        return dict(id=self.id, title=self.title, detail=detail or self.artist,
                    duration=self.duration, available=self.available, kind="track")


@dataclass(frozen=True)
class Page:
    rows: list
    more: bool = False
    note: str = ""


@dataclass(frozen=True)
class Stream:
    track: Track
    url: str = field(repr=False)


@dataclass(frozen=True)
class WaveBatch:
    station: str
    batch: str
    tracks: list[Track]


def track_model(track):
    albums = getattr(track, "albums", None) or []
    return Track(str(track.id), track.title or "Без названия",
                 ", ".join(a.name for a in track.artists or []),
                 (track.duration_ms or 0) / 1000, track.available is True,
                 str(albums[0].id) if albums else "")


class MusicApi:
    def __init__(self, client=None):
        private_logging()
        self.client = client or Client(request=Request(timeout=8))
        self.authenticated = False
        self._likes = []

    def login(self, on_code, cancel: Event):
        code = self.client.request_device_code(device_name="Yanjaro Music")
        url = urlsplit(code.verification_url)
        if (url.scheme != "https" or url.hostname not in
                {"oauth.yandex.ru", "oauth.yandex.com", "ya.ru", "passport.yandex.ru"}
                or url.username or url.password or url.port not in (None, 443)):
            raise ApiError("Получен неподдерживаемый адрес входа.")
        deadline = time.monotonic() + min(code.expires_in, 600)
        interval = max(1, code.interval)
        on_code(code.verification_url, code.user_code)
        try:
            while not cancel.wait(interval):
                if time.monotonic() >= deadline:
                    raise ApiError("Время входа истекло. Начните вход заново.")
                try:
                    token = self.client.poll_device_token(code.device_code)
                except DeviceAuthError as exc:
                    if "slow_down" in str(exc):
                        interval += 5
                        continue
                    raise
                if token is not None:
                    if cancel.is_set():
                        break
                    self.client.token = token.access_token
                    self.client.request.set_authorization(token.access_token)
                    self.client.init()
                    if cancel.is_set():
                        break
                    if not self.client.me or not self.client.me.account.uid:
                        raise ApiError("Не удалось подтвердить аккаунт.")
                    self.authenticated = True
                    return "Вход выполнен"
            raise ApiError("Вход отменён.")
        finally:
            if not self.authenticated:
                self.logout()

    def logout(self):
        self.authenticated = False
        self.client.token = None
        self.client.request.headers.pop("Authorization", None)
        self.client.me = None
        self.client.account_uid = None
        self._likes = []

    def _require_login(self):
        if not self.authenticated:
            raise ApiError("Сначала войдите через браузер.")

    def likes(self, page=0):
        self._require_login()
        if page == 0:
            result = self.client.users_likes_tracks()
            if result is None:
                raise ApiError("Не удалось получить «Мне нравится».")
            self._likes = [str(t.track_id) for t in result.tracks]
        ids = self._likes[page * 50:(page + 1) * 50]
        tracks = {str(t.id): track_model(t) for t in self.client.tracks(ids)} if ids else {}
        rows = [tracks[i.split(":")[0]].row() if i.split(":")[0] in tracks else
                dict(id=i, title="Трек недоступен", detail="Метаданные не получены",
                     duration=0, available=False, kind="track") for i in ids]
        return Page(rows, (page + 1) * 50 < len(self._likes))

    def search(self, text, page=0):
        self._require_login()
        text = text.strip()
        if not text or len(text) > 300:
            raise ApiError("Введите название песни длиной до 300 символов.")
        result = self.client.search(text, type_="track", page=page)
        if result is None:
            raise ApiError("Не удалось получить результаты поиска.")
        found = result.tracks
        return Page([track_model(t).row() for t in found.results] if found else [],
                    bool(found and (page + 1) * found.per_page < found.total))

    def stream(self, track_id):
        self._require_login()
        tracks = self.client.tracks([track_id])
        if not tracks or tracks[0].available is not True:
            raise ApiError("Полный трек недоступен для этого аккаунта или региона.")
        variants = self.client.tracks_download_info(track_id)
        full = [v for v in variants if v.preview is False and v.codec in {"mp3", "aac"}]
        if not full:
            raise ApiError("Полного аудио нет: сервис вернул только превью или неподдерживаемый формат.")
        variant = max(full, key=lambda v: v.bitrate_in_kbps)
        url = variant.get_direct_link()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ApiError("Сервис вернул неподдерживаемую ссылку на аудио.")
        return Stream(track_model(tracks[0]), url)

    def stations(self):
        self._require_login()
        stations = self.client.rotor_stations_list()
        return Page([dict(id=f"{s.station.id.type}:{s.station.id.tag}",
                          title=s.station.name, detail="Радиостанция", duration=0,
                          available=True, kind="station") for s in stations])

    def wave_batch(self, station, previous=None, start=False):
        self._require_login()
        if start:
            self.feedback(station, "radioStarted")
        # SDK 3.2.0 replaces settings2 with queue instead of merging the parameters.
        params = {"settings2": "True"}
        if previous:
            params["queue"] = previous
        data = self.client.request.get(f"{self.client.base_url}/rotor/station/{station}/tracks", params)
        result = StationTracksResult.de_json(data, self.client)
        if result is None or not result.batch_id:
            raise ApiError("Сервис не вернул партию треков волны.")
        tracks = [track_model(s.track) for s in result.sequence if s.type == "track" and s.track]
        return WaveBatch(station, result.batch_id, tracks)

    def feedback(self, station, event, track_id=None, batch=None, seconds=None):
        self._require_login()
        if not self.client.rotor_station_feedback(
                station, event, track_id=track_id, batch_id=batch,
                total_played_seconds=seconds, from_="yanjaro-music"):
            raise ApiError("Яндекс не принял событие волны. Следующая партия может повторяться.")

    def report_play(self, track, play_id, started_at, seconds, position):
        self._require_login()
        if not track.album_id:
            raise ApiError("Прослушивание не отправлено: у трека нет идентификатора альбома.")
        if not self.client.play_audio(
                track.id, from_="yanjaro-music", album_id=track.album_id, play_id=play_id,
                timestamp=started_at, track_length_seconds=round(track.duration),
                total_played_seconds=seconds, end_position_seconds=position):
            raise ApiError("Яндекс не подтвердил запись прослушивания. История может не обновиться.")

    def history(self):
        self._require_login()
        history = self.client.music_history(full_models_count=100)
        if history is None or history.history_tabs is None:
            raise ApiError("Не удалось прочитать историю аккаунта.")
        rows = []
        for tab in history.history_tabs:
            for group in tab.items or []:
                for item in group.tracks or []:
                    if item.type != "track" or not item.data:
                        continue
                    if item.data.full_model:
                        track = track_model(item.data.full_model)
                        rows.append(track.row(f"{tab.date} · {track.artist}"))
                    elif item.data.item_id and item.data.item_id.track_id:
                        # History may contain IDs only. Keep the gap visible, don't invent metadata.
                        rows.append(dict(id=str(item.data.item_id.track_id), title="Трек из истории",
                                         detail=f"{tab.date} · метаданные не получены", duration=0,
                                         available=False, kind="track"))
        return Page(rows, note="Показаны записи сервера Яндекса. Новые прослушивания этого клиента могут не появляться в серверной истории.")
