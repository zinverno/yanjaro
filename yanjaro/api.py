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
from .catalog import classify


class ApiError(Exception):
    """A fixed, safe message, never a server response or a URL."""


class InvalidAccount(ApiError):
    pass


class AccountRequest(Request):
    def _handle_error_response(self, status_code, content):
        # SDK 3.2 conflates 401 and 403. Only a confirmed 401 invalidates access.
        if status_code == 401:
            raise InvalidAccount('Сохранённый вход недействителен. Войдите заново.')
        if status_code == 403:
            raise ApiError('Доступ к этой функции ограничен. Сохранённый аккаунт не удалён.')
        return super()._handle_error_response(status_code, content)


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
    cover: str = ""
    artists: tuple = ()
    album_title: str = ""

    def row(self, detail=""):
        return dict(id=self.id, title=self.title, detail=detail or self.artist,
                    artist=self.artist, cover=self.cover, artists=list(self.artists), albumId=self.album_id, albumTitle=self.album_title,
                    duration=self.duration, available=self.available, kind="track")


@dataclass(frozen=True)
class Page:
    rows: list
    more: bool = False
    note: str = ""
    total: int = -1
    ids: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Stream:
    track: Track
    url: str = field(repr=False)


@dataclass(frozen=True)
class WaveBatch:
    station: str
    batch: str
    tracks: list[Track]


def artwork(uri, size='300x300'):
    if not isinstance(uri, str) or not uri:
        return ''
    url = uri if uri.startswith('https://') else 'https://' + uri.lstrip('/')
    url = url.replace('%%', size)
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'avatars.yandex.net', 'avatars.mds.yandex.net'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        return ''
    return url


def artist_links(artists):
    return tuple(dict(id=str(a.id), title=a.name or 'Исполнитель') for a in artists or [] if getattr(a, 'id', None))


def track_model(track):
    albums = getattr(track, 'albums', None) or []
    return Track(str(track.id), track.title or 'Без названия',
                 ', '.join(a.name for a in track.artists or []),
                 (track.duration_ms or 0) / 1000, track.available is True,
                 str(albums[0].id) if albums else '', artwork(getattr(track, 'cover_uri', None), '100x100'),
                 artist_links(track.artists), getattr(albums[0], 'title', '') or '' if albums else '')


def entity_row(entity, kind):
    if kind == 'track':
        return track_model(entity).row()
    artists = getattr(entity, 'artists', []) or []
    cover = getattr(entity, 'cover', None)
    uri = getattr(cover, 'uri', '') if cover else ''
    return dict(id=str(entity.id), kind=kind, title=(entity.name if kind == 'artist' else entity.title) or 'Без названия',
                cover=artwork(uri or getattr(entity, 'cover_uri', '') or getattr(entity, 'og_image', '')),
                artist=', '.join(a.name for a in artists), artists=list(artist_links(artists)),
                detail='Исполнитель' if kind == 'artist' else ', '.join(a.name for a in artists),
                year=getattr(entity, 'year', None) or '', duration=0, available=True)


def station_row(station):
    id = f'{station.id.type}:{station.id.tag}'
    parent = getattr(station, 'parent_id', None)
    parent = f'{parent.type}:{parent.tag}' if parent else ''
    origin = getattr(station, 'id_for_from', '')
    group, icon = classify(id, parent, origin)
    art = getattr(station, 'icon', None)
    return dict(id=id, title=station.name, detail=group, group=group, fallback=icon,
                parentId=parent, origin=origin, cover=artwork(getattr(art, 'image_url', '')),
                duration=0, available=True, kind='station')


class MusicApi:
    def __init__(self, client=None):
        private_logging()
        self.client = client or Client(request=AccountRequest(timeout=8))
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
                    return str(self.client.me.account.uid)
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

    def restore(self, token):
        self.client.token = token
        self.client.request.set_authorization(token)
        self.client.init()
        if not self.client.me or not self.client.me.account.uid:
            raise ApiError('Не удалось подтвердить аккаунт. Повторите доступ.')
        self.authenticated = True
        return str(self.client.me.account.uid)

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
        return Page(rows, (page + 1) * 50 < len(self._likes), total=len(self._likes),
                    ids=tuple(self._likes))

    def track_rows(self, ids):
        self._require_login()
        return [track_model(t).row() for t in self.client.tracks(ids)]

    def search(self, text, page=0, type_='track'):
        self._require_login()
        text = text.strip()
        if not text or len(text) > 300 or type_ not in {'all','track','artist','album'}:
            raise ApiError('Введите запрос длиной до 300 символов.')
        result = self.client.search(text, type_=type_, page=page)
        if result is None:
            raise ApiError('Не удалось получить результаты поиска.')
        if type_ != 'all':
            found = getattr(result, type_ + 's', None)
            return Page([entity_row(t, type_) for t in found.results] if found else [],
                        bool(found and (page + 1) * found.per_page < found.total),
                        total=found.total if found else 0)
        rows = []
        best = getattr(result, 'best', None)
        if best and best.type in {'track','artist','album'} and best.result:
            rows.append(dict(entity_row(best.result, best.type), section='Лучший результат'))
        for kind, heading in [('track','Треки'),('artist','Исполнители'),('album','Альбомы')]:
            found = getattr(result, kind + 's', None)
            if found:
                rows.extend(dict(entity_row(e, kind), section=heading) for e in found.results[:6])
        return Page(rows)

    def entity(self, kind, id, page=0):
        self._require_login()
        if not str(id).isdigit():
            raise ApiError('Некорректный идентификатор каталога.')
        if kind == 'album':
            album = self.client.albums_with_tracks(id)
            if not album:
                raise ApiError('Не удалось загрузить альбом.')
            rows = []
            for disc, tracks in enumerate(album.volumes or [], 1):
                for position, track in enumerate(tracks, 1):
                    row = track_model(track).row()
                    row.update(albumId=str(album.id), albumTitle=album.title,
                               section=f'Диск {disc}' if len(album.volumes) > 1 else '',
                               key=f'{disc}:{position}:{track.id}')
                    rows.append(row)
            return Page(rows, total=len(rows), meta=entity_row(album, 'album'))
        if kind == 'artist':
            brief = self.client.artists_brief_info(id) if page == 0 else None
            found = self.client.artists_tracks(id, page=page, page_size=50)
            if not found or (page == 0 and (not brief or not brief.artist)):
                raise ApiError('Не удалось загрузить исполнителя.')
            meta = entity_row(brief.artist, 'artist') if brief else {}
            if brief:
                meta['albums'] = [entity_row(a, 'album') for a in (brief.albums or [])[:6]]
            total = found.pager.total if found.pager else -1
            return Page([track_model(t).row() for t in found.tracks],
                        (page + 1) * 50 < total, total=total, meta=meta)
        if kind == 'artist-albums':
            found = self.client.artists_direct_albums(id, page=page, page_size=20)
            if not found:
                raise ApiError('Не удалось загрузить альбомы исполнителя.')
            total = found.pager.total if found.pager else -1
            return Page([entity_row(a, 'album') for a in found.albums], (page + 1) * 20 < total,
                        total=total, meta={'title':'Альбомы исполнителя'})
        raise ApiError('Раздел каталога не поддерживается.')

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
        return Page([station_row(s.station) for s in stations])

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
