"""Qt state and queues; the existing API remains confined to one worker thread."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import random
from threading import Event
import time
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices

from .api import MusicApi, safe_error, InvalidAccount
from .storage import data_path, read_json, write_json, account_path
from .catalog import station_groups
from .recommend import Profile, mix


def empty_page():
    return dict(rows=[], more=False, total=-1, ids=(), page=0, scroll=0.0,
                status="idle", error="", revision=0, meta={})


class PlaybackController(QObject):
    changed = Signal()
    contentChanged = Signal()
    queueChanged = Signal()
    likesChanged = Signal()
    _result = Signal(int, str, object, str)
    _code = Signal(int, str, str)

    def __init__(self, player, api=None, store=None):
        super().__init__()
        self.api = api or MusicApi()
        self.store = store
        self.account_generation = 0
        self.account_id = ''
        self.auth_job = None
        self.preferences = read_json(data_path('config', 'settings.json')) if store else {}
        self.storage_action = 'restore'
        self.saved = False
        self.player = player
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music-api")
        self.cancel = Event()
        self.play_cancel = Event()
        self.closing = False
        self.pages = {name: empty_page() for name in ("likes", "search", "stations", "history", "experiment")}
        self.search_type = 'all'
        self.search_pages = {kind: empty_page() for kind in ('all','track','artist','album')}
        self.pages.update({'search:' + kind: page for kind, page in self.search_pages.items()})
        self.pages['search'] = self.search_pages['all']
        self.back_stack = []
        self.profile = Profile()
        self.mix_revision = 0
        self.mix_job = None
        self.mix_steps = []
        self.mix_candidates = []
        self.mix_warnings = []
        self.mix_seed = 0
        self.mix_liked = set()
        self.liked_ids = set()
        self.likes_ready = False
        self.like_pending = {}
        self.like_jobs = {}
        self.like_refresh_needed = False
        self.station_preferences = {}
        self.station_query = ''
        self.station_groups = []
        self.page_jobs = {}
        self.play_job = self.meta_job = self.wave_job = None
        self.query = ""
        self.search_generation = 0
        self.queue_search_generation = -1
        self.queue = []
        self.queue_index = -1
        self.queue_context = ""
        self.queue_page_key = ""
        self.base_order = {}
        self.queue_history = []
        self.history_cursor = -1
        self.history_target = None
        self.repeat_mode = 'None'
        self.shuffle_enabled = False
        self.desired_paused = False
        self.stop_requested = False
        self.wave_station = ""
        self.wave_queue = []
        self.wave_seen = []
        self.wave_batches_received = 0
        self.wave_played_batches = set()
        self.generation = 0
        self.play_revision = 0
        self.active_wave = None
        self.wave_started = False
        self.refilling = False
        self.waiting_wave = False
        self.previous = None
        self.listened = 0.0
        self.experiment_seconds = 0.0
        self.current_track = None
        self.selected_row = None
        self.play_session = None
        self.was_playing = False
        self.last_tick = time.monotonic()
        self._state = dict(signedIn=False, authBusy=False, authError="", code="", loginUrl="",
                           remember=self.preferences.get('remember', True), accountMessage='',
                           storageAction='restore', mprisStatus='Системное управление не подключено',
                           view="likes", currentId="", current="Ничего не выбрано", artist="",
                           cover="", source="", loading=False, playerError=player.error,
                           stationError="", likeError="", waveActive=False,
                           playReport="События этого запуска ещё не отправлялись.")
        self._result.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self._code.connect(self._show_code, Qt.ConnectionType.QueuedConnection)
        player.changed.connect(self._player_changed)
        player.failed.connect(self._player_error)
        player.started.connect(self._started)
        player.ended.connect(self._ended)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._timer_tick)
        self.timer.start(200)

    @Property("QVariantMap", notify=contentChanged)
    def content(self):
        page = self.pages[self._state["view"]]
        return dict(rows=page['rows'], view=self._page_key(), scroll=page['scroll'], meta=page['meta'])

    @Property('QVariantList', notify=contentChanged)
    def stationGroups(self):
        return self.station_groups

    @Property('QVariantMap', notify=likesChanged)
    def likesState(self):
        # Updated only by likesChanged, rather than reconstructing 1000+ IDs
        # on the 200ms player position notification.
        return dict(ready=self.likes_ready,
                    liked={track_id: True for track_id in self.liked_ids},
                    pending={track_id: True for track_id in self.like_pending})

    def _page_key(self):
        return 'search:' + self.search_type if self._state['view'] == 'search' else self._state['view']

    @Property("QVariantList", notify=queueChanged)
    def queueRows(self):
        if self.wave_station:
            current = [dict(self.selected_row, queueIndex=-1, isCurrent=True)] if self.selected_row else []
            return current + [dict(t.row(), queueIndex=i, isCurrent=False) for i, (t, _) in enumerate(self.wave_queue)]
        return [dict(row, queueIndex=i, isCurrent=i == self.queue_index) for i, row in enumerate(self.queue) if i >= self.queue_index]

    def playback_status(self):
        if self._state['playerError']:
            return 'error'
        if self._state['loading']:
            return 'loading'
        if not self._state['currentId']:
            return 'empty'
        if not self.player.state['loaded']:
            return 'stopped'
        if self.player.state['paused']:
            return 'paused'
        return 'buffering' if self.player.state['buffering'] else 'playing'

    @Property("QVariantMap", notify=changed)
    def state(self):
        page = self.pages[self._state["view"]]
        headings = {"likes": "Мне нравится", "search": "Результаты поиска",
                    "stations": "Станции", "history": "История Яндекса", "experiment": "Подбор Yanjaro · эксперимент"}
        return self._state | self.player.state | dict(
            more=page["more"], total=page["total"], loadedCount=len(page["rows"]),
            pageStatus=page["status"], pageError=page["error"], pageScroll=page["scroll"],
            busy=page["status"] == "loading" or self._state["authBusy"],
            heading=headings.get(self._state['view'], page['meta'].get('title', 'Каталог')),
            experimentEnabled=self.profile.data['enabled'], experimentBalance=self.profile.data['balance'],
            experimentSeeds=len(self.profile.data['seeds']), experimentMessage=' '.join(self.mix_warnings),
            experimentRating=self.profile.data['ratings'].get(self._state['currentId'], {}).get('value', 0),
            searchType=self.search_type, canBack=bool(self.back_stack), currentRow=self.selected_row or {},
            entityKind=self._state['view'].split(':')[0], query=self.query,
            playbackStatus=self.playback_status(), desiredPaused=self.desired_paused,
            canPause=bool(self._state['currentId']) and self.playback_status() not in ('error', 'empty'),
            finiteQueue=bool(self.queue) and not self.wave_station,
            repeatMode=self.repeat_mode if not self.wave_station else 'None',
            shuffle=self.shuffle_enabled if not self.wave_station else False,
            canPrevious=not self.wave_station and self._previous_cursor() >= 0,
            canNext=bool(self.wave_station or self.history_cursor < len(self.queue_history) - 1
                         or any(r['available'] for r in self.queue[self.queue_index + 1:])
                         or self.repeat_mode == 'Playlist' and any(r['available'] for r in self.queue)),
            stationId=self.wave_station, refilling=self.refilling)

    def _work(self, operation, context, call):
        account = self.account_generation
        def run():
            try:
                result = call()
                self._result.emit(account, operation, (context, result), "")
            except Exception as exc:
                self._result.emit(account, operation, (context, None), safe_error(exc))
        return self.pool.submit(run)

    @Slot(int, str, object, str)
    def _deliver(self, account, operation, payload, error):
        if account == self.account_generation:
            self._completed(operation, payload, error)

    @Slot(str, object, str)
    def _completed(self, operation, payload, error):
        if self.closing:
            return
        context, result = payload
        if operation == "page":
            view, revision, number = context
            page = self.pages[view]
            if revision != page["revision"]:
                return
            page["error"] = error
            page["status"] = "error" if error else "ready"
            if not error:
                old = page["rows"] if number else []
                ids = {r.get("key", (r["kind"], r["id"], r.get("section", ""))) for r in old}
                rows = list(old)
                for row in result.rows:
                    key = row.get('key', (row['kind'], row['id'], row.get('section','')))
                    if key not in ids:
                        rows.append(row)
                        ids.add(key)
                page.update(rows=rows, more=result.more, total=result.total, page=number)
                if result.meta:
                    page['meta'] = result.meta
                if result.ids:
                    page["ids"] = result.ids
                if view == 'likes' and number == 0:
                    page['ids'] = result.ids  # Empty collection must clear old IDs.
                    self.likes_ready = True
                    self._sync_likes(result.ids)
                # The playing context is a snapshot. Only its own next search page can extend it.
                if (view == self.queue_page_key and number and self.queue_context == self.query
                        and self.queue_search_generation == self.search_generation and not self.wave_station):
                    existing = {r["id"] for r in self.queue}
                    self.queue.extend(r.copy() for r in rows if r["id"] not in existing and r["available"])
                    for row in self.queue:
                        self.base_order.setdefault(row['id'].split(':')[0], len(self.base_order))
                if view == 'stations':
                    self._refresh_stations()
                self.contentChanged.emit()
        elif operation == 'account':
            self._state.update(authBusy=False, code='', loginUrl='', authError=error)
            if not error:
                self.account_id = result.get('uid', '')
                self.saved = result.get('saved', False)
                self._state.update(signedIn=bool(self.account_id), accountMessage=result.get('message', ''),
                                   authError=result.get('error', ''))
                self.storage_action = result.get('action', 'restore')
                self._state['storageAction'] = self.storage_action
                if self.account_id:
                    self.station_preferences = read_json(account_path(self.account_id, 'stations.json')) if self.store else {}
                    self.profile = Profile(self.account_id, persistent=bool(self.store))
                    self.preferences['signed_out'] = False
                    self._save_preferences()
                    self.show('likes')
        elif operation == 'secret':
            self._state.update(authBusy=False, accountMessage=error or ('Вход сохранён в Secret Service.' if context == 'save' else 'Сохранённый вход удалён.'))
            self.saved = context == 'save' and not error
            self.storage_action = context if error else 'restore'
            self._state['storageAction'] = self.storage_action
        elif operation == 'logout':
            self._state.update(authBusy=False, authError=error, accountMessage=error or 'Вы вышли из аккаунта.')
            self.storage_action = 'delete' if error else 'restore'
            self._state['storageAction'] = self.storage_action
            self.saved = False
        elif operation == "play":
            if context != (self.generation, self.play_revision):
                return
            if error:
                self._player_error(error)
            else:
                self.current_track = result.track
                self.listened = 0.0
                self.experiment_seconds = 0.0
                self._set_current(result.track.row())
                if not self.wave_station and self.queue_index >= 0:
                    self.queue[self.queue_index] = result.track.row()
                self.player.play(result, paused=self.desired_paused)
        elif operation == 'like':
            track_id, was_liked = context
            if track_id not in self.like_pending:
                return
            self.like_pending.pop(track_id)
            self.like_jobs.pop(track_id, None)
            if error:
                if was_liked:
                    self.liked_ids.add(track_id)
                else:
                    self.liked_ids.discard(track_id)
                self._state['likeError'] = 'Не удалось изменить «Мне нравится». ' + error
                self.likesChanged.emit()
            else:
                self._sync_likes(result)
                likes = self.pages['likes']
                likes['ids'] = tuple(result)
                likes['total'] = len(result)
                self.like_refresh_needed = True
            if not self.like_pending and self.like_refresh_needed:
                self.like_refresh_needed = False
                self.pages['likes']['scroll'] = 0
                self._load_page('likes', 0)  # Reset pagination offsets after mutation.
            self.contentChanged.emit()
        elif operation == "queue-meta":
            if context != self.generation or error:
                return
            by_id = {r["id"]: r for r in result}
            self.queue = [by_id.get(r["id"].split(":")[0], r) for r in self.queue]
        elif operation == "wave":
            if context != self.generation:
                return
            self.refilling = False
            if error:
                self._state["stationError"] = "Не удалось продолжить станцию. " + error
            else:
                self.wave_batches_received += 1
                self._append_wave(result)
                if not self.wave_queue:
                    self._state["stationError"] = "Не удалось продолжить станцию: нет новых доступных треков."
            if self.waiting_wave:
                self.waiting_wave = False
                if self.wave_queue:
                    self._take_wave()
                else:
                    self._state["loading"] = False
        elif operation == 'experiment-step':
            revision, step = context
            if revision != self.mix_revision or not self.profile.data['enabled']:
                return
            self._mix_result(step, result, error)
        elif operation == "play-report":
            self._state["playReport"] = error or "Событие прослушивания принято сервером. Обновление истории этим не подтверждено."
        elif operation == "feedback" and context == self.generation and error:
            self._state["stationError"] = error
        self.queueChanged.emit()
        self.changed.emit()

    @Slot(int, str, str)
    def _show_code(self, account, url, code):
        if self.closing or self.cancel.is_set() or account != self.account_generation:
            return
        self._state.update(code=code, loginUrl=url)
        self.open_browser()
        self.changed.emit()

    @Slot()
    def open_browser(self):
        if self._state["loginUrl"] and not QDesktopServices.openUrl(QUrl(self._state["loginUrl"])):
            self._state["authError"] = "Браузер не открылся. Откройте адрес рядом с кодом."
            self.changed.emit()

    def _save_preferences(self):
        if self.store:
            try:
                write_json(data_path('config', 'settings.json'), self.preferences)
            except OSError:
                self._state['accountMessage'] = 'Не удалось записать настройки устройства.'

    @Slot(bool)
    def remember_account(self, enabled):
        self._state['remember'] = enabled
        self.preferences['remember'] = enabled
        self._save_preferences()
        if self._state['signedIn']:
            self.storage_action = 'save' if enabled else 'delete'
            self.retry_storage()
        self.changed.emit()

    def _sync_likes(self, full_ids):
        updated = {str(item).split(':', 1)[0] for item in full_ids}
        # In-flight optimistic changes take precedence over stale page results.
        for track_id, intended in self.like_pending.items():
            if intended:
                updated.add(track_id)
            else:
                updated.discard(track_id)
        self.liked_ids = updated
        self.likesChanged.emit()

    @Slot(str, str)
    def toggle_like(self, track_id, album_id):
        track_id = str(track_id)
        base = track_id.split(':', 1)[0]
        if (not self._state['signedIn'] or not self.likes_ready or
                not base.isdecimal() or base in self.like_pending):
            return
        was_liked = base in self.liked_ids
        intended = not was_liked
        self.like_pending[base] = intended
        if intended:
            self.liked_ids.add(base)
        else:
            self.liked_ids.discard(base)
        self._state['likeError'] = ''
        self.likesChanged.emit()
        self.changed.emit()
        account = self.account_generation
        def change():
            if self.closing or account != self.account_generation:
                return ()
            return self.api.set_track_liked(track_id, intended, album_id)
        self.like_jobs[base] = self._work('like', (base, was_liked), change)

    @Slot()
    def clear_like_error(self):
        self._state['likeError'] = ''
        self.changed.emit()

    def restore_account(self, unlock=False):
        if not self.store or self._state['authBusy'] or not self._state['remember']:
            return
        if self.preferences.get('signed_out'):
            return
        self._state.update(authBusy=True, authError='', accountMessage='Проверяем сохранённый аккаунт…')
        def restore():
            try:
                token = self.store.read(unlock=unlock)
            except Exception as exc:
                return dict(error=safe_error(exc), action='restore')
            if not token:
                return dict(message='Сохранённого аккаунта нет.')
            try:
                uid = self.api.restore(token)
            except InvalidAccount as exc:
                return dict(error=safe_error(exc), action='delete')
            except Exception as exc:
                return dict(error=safe_error(exc) + ' Сохранённый вход оставлен; повторите доступ.', action='restore')
            return dict(uid=uid, saved=True, message='Вход восстановлен из Secret Service.')
        self.auth_job = self._work('account', None, restore)
        self.changed.emit()

    @Slot()
    def retry_storage(self):
        if not self.store or self._state['authBusy']:
            return
        if self.storage_action == 'restore':
            self.restore_account(unlock=True)
            return
        action = self.storage_action
        self._state.update(authBusy=True, authError='')
        self.auth_job = self._work('secret', action, self.store.delete if action == 'delete'
                                  else lambda: self.store.write(self.api.client.token))
        self.changed.emit()

    @Slot()
    def login(self):
        if self._state['authBusy'] or self._state['signedIn']:
            return
        cancel = self.cancel = Event()
        account = self.account_generation
        self._state.update(authBusy=True, authError='')
        remember = self._state['remember']
        def login():
            uid = self.api.login(lambda url, code: self._code.emit(account, url, code), cancel)
            if cancel.is_set():
                self.api.logout()
                return {}
            result = dict(uid=uid, saved=False, message='Вход только на этот сеанс.')
            if remember and self.store:
                try:
                    self.store.write(self.api.client.token)
                    result.update(saved=True, message='Вход сохранён в Secret Service.')
                except Exception as exc:
                    result.update(message='Вход выполнен только на этот сеанс. ' + safe_error(exc), action='save')
            return result
        self.auth_job = self._work('account', None, login)
        self.changed.emit()

    @Slot()
    def cancel_login(self):
        self.cancel.set()
        self.account_generation += 1
        if self.auth_job:
            self.auth_job.cancel()
        if self.store:
            self.store.abort()
        self._work('cancel-auth', None, self.api.logout)
        self._state.update(code="", loginUrl="", authBusy=False)
        self.changed.emit()

    @Slot()
    def logout(self):
        if self._state["authBusy"]:
            return
        self.cancel.set()
        self.play_cancel.set()
        self.account_generation += 1
        for job in self.page_jobs.values():
            job.cancel()
        self.preferences['signed_out'] = True
        self._save_preferences()
        self.account_id = ''
        self.station_preferences = {}
        self.station_groups = []
        self.liked_ids.clear()
        self.likes_ready = False
        for job in self.like_jobs.values():
            job.cancel()
        self.like_jobs.clear()
        self.like_pending.clear()
        self.like_refresh_needed = False
        self._state['likeError'] = ''
        self.likesChanged.emit()
        self.back_stack = []
        self._leave_wave()
        self.cancel_mix()
        self.profile = Profile()
        self.repeat_mode = 'None'
        self.shuffle_enabled = False
        self.queue = []
        self.queue_history = []
        self.history_cursor = -1
        self.queue_index = -1
        self.current_track = None
        self.selected_row = None
        self.player.stop()
        for page in self.pages.values():
            revision = page["revision"] + 1
            page.update(empty_page(), revision=revision)
        self._state.update(signedIn=False, authBusy=True, currentId="", current="Ничего не выбрано",
                           artist="", cover="", source="", loading=False, playerError="")
        def logout():
            self.api.logout()
            if self.store:
                self.store.delete()
        self.auth_job = self._work('logout', None, logout)
        self.contentChanged.emit()
        self.queueChanged.emit()
        self.changed.emit()

    def _load_page(self, view, number=0):
        if view == 'search':
            view = 'search:' + self.search_type
        page = self.pages[view]
        page["revision"] += 1
        page.update(status="loading", error="")
        context = view, page["revision"], number
        query = self.query
        if previous := self.page_jobs.get(view):
            previous.cancel()  # Queued obsolete searches never reach the network.
        def call():
            if view == "stations":
                return self.api.stations()
            if view == "history":
                return self.api.history()
            if view.startswith('search:'):
                return self.api.search(query, number, view.split(':')[1])
            if ':' in view:
                kind, id = view.split(':', 1)
                return self.api.entity(kind, id, number)
            return self.api.likes(number)
        self.page_jobs[view] = self._work("page", context, call)
        self.changed.emit()

    @Slot(str)
    def show(self, view):
        if view not in self.pages:
            return
        self._state['view'] = view
        if view == 'stations':
            self._refresh_stations()
        self.contentChanged.emit()
        page = self.pages[view]
        if self._state["signedIn"] and view != "experiment" and page["status"] == "idle" and (view != "search" or self.query):
            self._load_page(view)
        self.changed.emit()

    @Slot(float)
    def save_scroll(self, position):
        self.pages[self._state["view"]]["scroll"] = max(0, position)

    @Slot(str)
    def search(self, query):
        self.query = query.strip()
        self.search_generation += 1
        self.back_stack = []
        for kind, page in self.search_pages.items():
            if previous := self.page_jobs.get('search:' + kind):
                previous.cancel()
            revision = page['revision'] + 1
            page.update(empty_page(), revision=revision)
        self._state['view'] = 'search'
        if self.query and self._state['signedIn']:
            self._load_page('search')
        self.contentChanged.emit()
        self.changed.emit()

    @Slot(str)
    def search_tab(self, kind):
        if kind not in self.search_pages:
            return
        self.search_type = kind
        self.pages['search'] = self.search_pages[kind]
        self.show('search')

    @Slot(str, str)
    def open_entity(self, kind, id):
        if kind not in ('artist','album','artist-albums') or not str(id).isdigit():
            return
        key = kind + ':' + str(id)
        if key == self._state['view']:
            return
        self.back_stack.append((self._state['view'], self.search_type))
        self.pages.setdefault(key, empty_page())
        self.show(key)

    @Slot()
    def back(self):
        if self.back_stack:
            view, kind = self.back_stack.pop()
            self.search_type = kind
            self.pages['search'] = self.search_pages[kind]
            self.show(view)

    def _refresh_stations(self):
        self.station_groups = station_groups(self.pages['stations']['rows'], self.station_preferences, self.station_query)
        self.contentChanged.emit()

    @Slot(str)
    def filter_stations(self, query):
        self.station_query = query
        self._refresh_stations()

    def _save_station_preferences(self):
        if self.store and self.account_id:
            try:
                write_json(account_path(self.account_id, 'stations.json'), self.station_preferences)
            except OSError:
                self.pages['stations']['error'] = 'Не удалось сохранить порядок станций на устройстве.'
                self.changed.emit()

    @Slot(str, str)
    def station_action(self, id, action):
        if action not in ('pins', 'hidden'):
            return
        values = self.station_preferences.setdefault(action, [])
        if id in values:
            values.remove(id)
        else:
            values.append(id)
        self._save_station_preferences()
        self._refresh_stations()

    @Slot()
    def retry_page(self):
        if not self._state["signedIn"]:
            return
        view = self._state["view"]
        page = self.pages[view]
        if view == "experiment":
            self.build_mix()
        elif page["status"] != "loading":
            self._load_page(view, page["page"] + 1 if page["rows"] and page["more"] else 0)

    @Slot()
    def more(self):
        view = self._state["view"]
        page = self.pages[view]
        if page["more"] and page["status"] == "ready":
            self._load_page(view, page["page"] + 1)

    def _set_current(self, row):
        self.selected_row = row.copy()
        self._state.update(currentId=row["id"].split(":")[0], current=row["title"],
                           artist=row.get("artist", row.get("detail", "")), cover=row.get("cover", ""))

    @Slot(str)
    def play(self, track_id):
        if self._state["view"] == "stations":
            self.start_wave(track_id)
            return
        if str(track_id).split(':')[0] == self._state['currentId']:
            if self.playback_status() in ('paused', 'loading', 'buffering', 'playing'):
                self.play_resume()
                return
        self.desired_paused = False  # Explicit row selection always requests playback.
        self.stop_requested = False
        self._build_queue(track_id)

    def _build_queue(self, track_id, shuffle=None):
        if not self.player.state["ready"]:
            self._player_error(self.player.error)
            return
        page = self.pages[self._state["view"]]
        rows = [r for r in page["rows"] if r["kind"] == "track"]
        self._leave_wave()
        self.queue_context = self.query if self._state["view"] == "search" else ""
        self.queue_page_key = self._page_key()
        self.queue_search_generation = self.search_generation
        by_id = {r["id"].split(":")[0]: r for r in rows}
        # The full likes ID list is returned by the existing likes endpoint, not inferred from a page.
        ids = page["ids"] if self._state["view"] == "likes" and page["ids"] else [r["id"] for r in rows]
        self.queue = [by_id.get(id.split(":")[0], dict(id=id, title="Трек из коллекции",
                      artist="Название загрузится перед воспроизведением", cover="", duration=0,
                      available=True, kind="track" )).copy() for id in dict.fromkeys(ids)]
        if not self.queue:
            self.queue = [dict(id=track_id, title="Загрузка трека", artist="", cover="", available=True)]
        self.base_order = {r['id'].split(':')[0]: i for i, r in enumerate(self.queue)}
        self.queue_history = []
        self.history_cursor = -1
        self.history_target = None
        if shuffle is not None:
            self.shuffle_enabled = shuffle
        if shuffle:
            random.shuffle(self.queue)
        self.queue_index = next((i for i, r in enumerate(self.queue) if r["available"]), -1) if shuffle else next((i for i, r in enumerate(self.queue) if r["id"].split(":")[0] == track_id.split(":")[0]), 0)
        while 0 <= self.queue_index < len(self.queue) and not self.queue[self.queue_index]["available"]:
            self.queue_index += 1
        self._state["source"] = "Поиск: " + self.query if self.queue_context else self.state["heading"]
        if not 0 <= self.queue_index < len(self.queue):
            self.player.stop()
            self.current_track = None
            self.selected_row = None
            self._state.update(currentId="", current="Ничего не выбрано", artist="", cover="", loading=False)
            self._player_error("В коллекции нет доступных треков.")
            self.queueChanged.emit()
            return
        if self.shuffle_enabled and not shuffle:
            self._reorder_remaining()
        self._play_queue()

    @Slot(bool)
    def play_collection(self, shuffle):
        page = self.pages["likes"]
        if not page["ids"]:
            return
        self._state["view"] = "likes"
        self.desired_paused = False
        self.stop_requested = False
        self._build_queue(page["ids"][0], shuffle)

    @Slot()
    def play_page(self):
        rows = self.pages[self._state['view']]['rows']
        first = next((r for r in rows if r['kind'] == 'track' and r['available']), None)
        if first:
            self.play(first['id'])

    def _load_track(self, row):
        self.play_cancel.set()
        self.play_cancel = cancel = Event()
        if self.play_job:
            self.play_job.cancel()
        self.play_revision += 1
        self.player.stop()
        self.current_track = None
        self._set_current(row)
        if self.stop_requested:
            self._state.update(loading=False, playerError='')
            if self.history_target is not None:
                self.history_cursor, self.history_target = self.history_target, None
            self.queueChanged.emit()
            self.changed.emit()
            return
        self._state.update(loading=True, playerError="")
        self.play_job = self._work("play", (self.generation, self.play_revision), lambda: self.api.stream(row["id"], cancel=cancel))
        self.queueChanged.emit()
        self.changed.emit()

    def _play_queue(self):
        if not 0 <= self.queue_index < len(self.queue):
            return
        self._load_track(self.queue[self.queue_index])
        upcoming = self.queue[self.queue_index + 1:self.queue_index + 11]
        ids = [r["id"] for r in upcoming if not r.get("duration")]
        if self.meta_job:
            self.meta_job.cancel()
        if ids:
            self.meta_job = self._work("queue-meta", self.generation, lambda: self.api.track_rows(ids))

    @Slot(int)
    def jump_queue(self, index, preserve_pause=False):
        if not preserve_pause and not self.wave_station and index == self.queue_index:
            self.play_resume()
            return
        if not preserve_pause:
            self.desired_paused = False
            self.stop_requested = False
        if self.wave_station:
            if not 0 <= index < len(self.wave_queue):
                return
            self._finish_track("skip", "manual-skip")
            self.wave_queue = self.wave_queue[index:]
            self._take_wave()
        elif 0 <= index < len(self.queue):
            self._finish_track("skip", "manual-skip")
            self.queue_index = index
            self._play_queue()

    def _history_select(self, cursor):
        id = self.queue_history[cursor]
        index = next((i for i, r in enumerate(self.queue) if r['id'].split(':')[0] == id), -1)
        if index >= 0:
            self.history_target = cursor
            self.jump_queue(index, preserve_pause=True)

    @Slot()
    def previous_track(self):
        self.stop_requested = self.playback_status() == 'stopped'
        cursor = self._previous_cursor()
        if not self.wave_station and cursor >= 0:
            self._history_select(cursor)

    def _previous_cursor(self):
        # A selection still loading has not entered playback history yet.
        if self.history_cursor >= 0 and self.queue_history[self.history_cursor] != self._state['currentId']:
            return self.history_cursor
        return self.history_cursor - 1

    @Slot()
    def next_track(self):
        self.stop_requested = self.playback_status() == 'stopped'
        self._advance(False)

    def _advance(self, natural):
        if self.wave_station:
            if not natural:
                self.next_wave()
            else:
                self._take_wave()
            return
        if natural and self.repeat_mode == 'Track' and self.queue:
            self._play_queue()
            return
        if not natural and self.history_cursor < len(self.queue_history) - 1:
            self._history_select(self.history_cursor + 1)
            return
        index = next((i for i in range(self.queue_index + 1, len(self.queue)) if self.queue[i]['available']), -1)
        if index < 0 and self.repeat_mode == 'Playlist' and self.queue:
            self.queue.sort(key=lambda r: self.base_order.get(r['id'].split(':')[0], len(self.base_order)))
            if self.shuffle_enabled:
                random.shuffle(self.queue)
                if len(self.queue) > 1 and self.queue[0]['id'].split(':')[0] == self._state['currentId']:
                    self.queue.append(self.queue.pop(0))
            index = next((i for i, row in enumerate(self.queue) if row['available']), -1)
        if index >= 0:
            self.jump_queue(index, preserve_pause=True)

    def _reorder_remaining(self):
        rest = self.queue[self.queue_index + 1:]
        if self.shuffle_enabled:
            random.shuffle(rest)
        else:
            rest.sort(key=lambda r: self.base_order.get(r['id'].split(':')[0], len(self.base_order)))
        self.queue[self.queue_index + 1:] = rest
        self.queueChanged.emit()
        self.changed.emit()

    @Slot(bool)
    def set_shuffle(self, enabled):
        if self.wave_station or self.shuffle_enabled == enabled:
            return
        self.shuffle_enabled = enabled
        self._reorder_remaining()

    @Slot(str)
    def set_repeat(self, mode):
        if not self.wave_station and mode in ('None', 'Playlist', 'Track'):
            self.repeat_mode = mode
            self.changed.emit()

    @Slot()
    def cycle_repeat(self):
        modes = ('None', 'Playlist', 'Track')
        self.set_repeat(modes[(modes.index(self.repeat_mode) + 1) % 3])

    def _player_changed(self):
        self._tick()
        self.changed.emit()

    def _timer_tick(self):
        self._tick()
        if self.mix_steps and self.mix_job is None:
            self._mix_next()

    def _tick(self):
        now = time.monotonic()
        state = self.player.state
        if self.play_session and self.was_playing:
            seconds = max(0, min(now - self.last_tick, 1))
            self.listened += seconds
            if self.profile.data['enabled']:
                self.experiment_seconds += seconds
        self.last_tick = now
        self.was_playing = bool(self.play_session and state['loaded'] and not state['paused']
                                and not state['buffering'] and not state.get('seeking', False))

    def _finish_track(self, event, cause="source-change"):
        self._tick()
        session, self.play_session = self.play_session, None
        if session:
            self.was_playing = False
            track, play_id, _ = session
            try:
                self.profile.record(play_id, track.id, self._state['source'], self.experiment_seconds, cause)
            except OSError:
                self.mix_warnings = ['Не удалось сохранить локальные события эксперимента.']
        if session and self.listened > 0:
            track, play_id, started_at = session
            seconds, position = self.listened, self.player.state["position"]
            self._work("play-report", None, lambda: self.api.report_play(track, play_id, started_at, seconds, position))
        active, self.active_wave = self.active_wave, None
        if active and self.wave_started:
            station, track_id, batch = active
            seconds = self.listened
            self.previous = track_id
            self._work("feedback", self.generation, lambda: self.api.feedback(station, event, track_id, batch, seconds))
        self.wave_started = False

    def _leave_wave(self):
        self.play_cancel.set()
        self._finish_track("skip")
        for job in (self.wave_job, self.play_job, self.meta_job):
            if job:
                job.cancel()
        self.generation += 1
        self.play_revision += 1
        self.wave_station = ""
        self.wave_queue = []
        self.wave_seen = []
        self.wave_batches_received = 0
        self.wave_played_batches = set()
        self.previous = None
        self.refilling = False
        self.waiting_wave = False
        self._state.update(waveActive=False, stationError="")

    @Slot(str)
    def start_wave(self, station):
        if not self._state["signedIn"]:
            return
        if not self.player.state["ready"]:
            self._player_error(self.player.error)
            return
        self._leave_wave()
        self.player.stop()
        self.queue = []
        self.queue_index = -1
        self.current_track = None
        self.wave_station = station
        self.selected_row = None
        name = next((r["title"] for r in self.pages["stations"]["rows"] if r["id"] == station),
                    "Моя волна" if station == "user:onyourwave" else "Станция")
        self.desired_paused = False
        self.stop_requested = False
        self._state.update(waveActive=True, source=name, loading=True, currentId="", current="Подбираем музыку",
                           artist="", cover="", playerError="")
        self.waiting_wave = True
        self._refill(start=True)

    def _append_wave(self, batch):
        excluded = set(self.wave_seen) | {t.id for t, _ in self.wave_queue}
        for track in batch.tracks:
            if track.available and track.id not in excluded:
                self.wave_queue.append((track, batch.batch))
                excluded.add(track.id)

    def _refill(self, start=False):
        if self.refilling or not self.wave_station or self._state["stationError"]:
            return
        self.refilling = True
        station, previous = self.wave_station, self.previous
        self.wave_job = self._work("wave", self.generation, lambda: self.api.wave_batch(station, previous, start=start))
        self.changed.emit()

    @Slot()
    def retry_station(self):
        self._state["stationError"] = ""
        self.waiting_wave = not self.player.state["loaded"]
        self._refill(start=self.previous is None and not self.wave_seen)

    def _take_wave(self):
        if not self.wave_station or self.closing:
            return
        if not self.wave_queue:
            self.waiting_wave = True
            self._state["loading"] = not bool(self._state["stationError"])
            self._refill()
            return
        track, batch = self.wave_queue.pop(0)
        self.wave_seen = (self.wave_seen + [track.id])[-100:]
        self.active_wave = (self.wave_station, track.id, batch)
        self.listened = 0.0
        self._load_track(track.row())

    @Slot()
    def next_wave(self):
        if not self.wave_station:
            return
        self._finish_track("skip", "manual-skip")
        self.player.stop()
        self._take_wave()

    @Slot()
    def _started(self):
        if self.closing or not self.current_track:
            return
        if not self.play_session:
            self.play_session = (self.current_track, str(uuid4()), datetime.now(timezone.utc).isoformat())
            self.last_tick = time.monotonic()
            if not self.wave_station:
                if self.history_target is not None:
                    self.history_cursor = self.history_target
                    self.history_target = None
                else:
                    self.queue_history = self.queue_history[:self.history_cursor + 1] + [self.current_track.id]
                    self.history_cursor = len(self.queue_history) - 1
        self._state["loading"] = False
        self.player.set_pause(self.desired_paused)
        if self.active_wave and not self.wave_started:
            self.wave_started = True
            station, track_id, batch = self.active_wave
            self.wave_played_batches.add(batch)
            recent = self.station_preferences.setdefault('recent', {})
            stat = recent.setdefault(station, {'count':0, 'last':0})
            stat.update(count=stat['count'] + 1, last=time.time())
            self._save_station_preferences()
            self._work("feedback", self.generation, lambda: self.api.feedback(station, "trackStarted", track_id, batch))
            self.previous = track_id
            if len(self.wave_queue) <= 2:
                self._refill()
        self.changed.emit()

    @Slot()
    def _ended(self):
        if self.closing:
            return
        self._finish_track("trackFinished", "finished")
        self._advance(True)
        self.changed.emit()

    @Slot()
    def retry_play(self):
        if self.wave_station and self.active_wave:
            track = self.current_track
            if track:
                self._load_track(track.row())
            else:
                self._load_track(dict(id=self.active_wave[1], title=self._state["current"], artist=self._state["artist"]))
        else:
            self._play_queue()

    @Slot()
    def pause(self):
        if not self._state['currentId']:
            return
        if self.playback_status() in ('stopped', 'error'):
            self.play_resume()
        else:
            self.set_paused(not self.desired_paused)

    def set_paused(self, paused):
        if self._state['currentId']:
            self.desired_paused = bool(paused)
            self.player.set_pause(self.desired_paused)
            self.changed.emit()

    @Slot()
    def play_resume(self):
        self.desired_paused = False
        self.stop_requested = False
        if self.playback_status() in ('paused', 'playing', 'buffering', 'loading'):
            self.player.set_pause(False)
        elif self.playback_status() in ('stopped', 'error'):
            self.retry_play()
        self.changed.emit()

    @Slot()
    def stop(self):
        self.play_cancel.set()
        self.stop_requested = True
        active = self.active_wave
        self._finish_track('skip', 'stop')
        self.active_wave = active  # Play can explicitly restart the selected radio track.
        for job in (self.play_job, self.wave_job, self.meta_job):
            if job:
                job.cancel()
        self.generation += 1
        self.play_revision += 1
        self.refilling = self.waiting_wave = False
        self.player.stop()
        self._state.update(loading=False, playerError='')
        self.changed.emit()

    @Slot(float)
    def seek(self, seconds):
        self.player.seek(seconds)

    @Slot(float)
    def volume(self, value):
        self.player.set_volume(value)

    @Slot()
    def mute(self):
        self.player.toggle_mute()

    @Slot(str)
    def _player_error(self, message):
        active = self.active_wave
        self._finish_track('skip', 'error')
        self.active_wave = active
        self._state.update(playerError=message, loading=False)
        self.changed.emit()

    def _save_profile(self):
        try:
            self.profile.save()
        except OSError:
            self.mix_warnings = ['Не удалось сохранить данные эксперимента на устройстве.']
        self.changed.emit()

    def cancel_mix(self):
        self.mix_revision += 1
        self.mix_steps = []
        if self.mix_job:
            self.mix_job.cancel()
        self.mix_job = None

    @Slot(bool)
    def enable_experiment(self, enabled):
        self._tick()
        self.cancel_mix()
        self.profile.data['enabled'] = enabled
        self._save_profile()
        if not enabled:
            self.pages['experiment'].update(empty_page())
            if self._state['view'] == 'experiment':
                self.show('likes')
        self.contentChanged.emit()

    @Slot(float)
    def experiment_balance(self, value):
        self.profile.data['balance'] = max(0, min(value, 1))
        self._save_profile()

    @Slot(int)
    def rate_experiment(self, value):
        try:
            self.profile.rate(self._state['currentId'], value)
            self.mix_warnings = ['Локальная оценка учтётся при следующей сборке. Лайки Яндекса не изменены.']
        except OSError:
            self.mix_warnings = ['Не удалось сохранить оценку эксперимента.']
        self.changed.emit()

    @Slot()
    def seed_experiment(self):
        if self.profile.data['enabled'] and self._state['currentId']:
            seeds = self.profile.data['seeds']
            if self._state['currentId'] not in seeds:
                self.profile.data['seeds'] = (seeds + [self._state['currentId']])[-10:]
            self._save_profile()

    @Slot()
    def clear_experiment(self):
        self.cancel_mix()
        self.experiment_seconds = 0.0
        enabled = self.profile.data['enabled']
        self.profile.data.update(enabled=enabled, events=[], ratings={}, seeds=[])
        self.pages['experiment'].update(empty_page())
        self.mix_warnings = ['Данные эксперимента очищены.']
        self._save_profile()
        self.contentChanged.emit()

    @Slot()
    def build_mix(self):
        if not self.profile.data['enabled'] or not self._state['signedIn']:
            return
        self.cancel_mix()
        self.mix_seed = random.randrange(2 ** 32)
        self.mix_candidates = []
        self.mix_warnings = ['Режим v0: коллекция и знакомые исполнители/альбомы. Похожие треки API ещё не включены.']
        self.pages['experiment'].update(empty_page(), status='loading')
        self.show('experiment')
        if self.pages['likes']['ids'] or self.pages['likes']['status'] == 'ready':
            self._mix_prepare(self.pages['likes']['ids'])
        else:
            self.mix_steps = [('likes', '')]
        self._mix_next()

    def _mix_prepare(self, ids):
        self.mix_liked = {id.split(':')[0] for id in ids}
        seeds = list(dict.fromkeys(list(ids) + self.profile.data['seeds']))
        rng = random.Random(self.mix_seed)
        seeds = rng.sample(seeds, min(60, len(seeds)))
        self.mix_steps = [('seeds', seeds)] if seeds else []
        if not seeds:
            self.pages['experiment'].update(status='ready', rows=[], total=0)
            self.mix_warnings.append('Коллекция пуста. Найдите музыку и добавьте несколько исходных треков кнопкой ниже.')
            self.contentChanged.emit(); self.changed.emit()

    def _mix_next(self):
        if not self.profile.data['enabled'] or not self.mix_steps or self.mix_job is not None:
            return
        foreground = [*self.page_jobs.values(), self.play_job, self.meta_job, self.wave_job, self.auth_job]
        if any(job and not job.done() for job in foreground):
            return  # One bounded request at a time, after pending playback/browse work.
        step = self.mix_steps.pop(0)
        def call():
            kind, source = step
            if kind == 'likes': return self.api.likes(0)
            if kind == 'seeds': return self.api.track_rows(source)
            return self.api.candidates(kind, source)
        self.mix_job = self._work('experiment-step', (self.mix_revision, step), call)

    def _mix_result(self, step, result, error):
        self.mix_job = None
        kind, source = step
        if error:
            self.mix_warnings.append('Часть кандидатов недоступна. ' + error)
        elif kind == 'likes':
            self._mix_prepare(result.ids)
        else:
            rows = result[:60 if kind == 'seeds' else 40]
            self.mix_candidates.extend(dict(r, origins=['liked' if r['id'] in self.mix_liked else 'seed' if kind == 'seeds' else kind]) for r in rows)
            if kind == 'seeds':
                artists = list(dict.fromkeys(a['id'] for r in rows for a in r.get('artists', [])))[:2]
                albums = list(dict.fromkeys(r['albumId'] for r in rows if r.get('albumId')))[:1]
                self.mix_steps.extend(('artist', id) for id in artists)
                self.mix_steps.extend(('album', id) for id in albums)
        if self.mix_steps:
            self._mix_next()
        else:
            rows = mix(self.mix_candidates, self.mix_liked, self.profile.data, self.mix_seed)
            self.pages['experiment'].update(rows=rows, total=len(rows), status='ready', more=False)
            self.mix_candidates = []  # No persistent catalogue/profile cache beyond the finite mix.
            self.contentChanged.emit()
            self.changed.emit()

    def close(self):
        self.play_cancel.set()
        self._finish_track("skip", "closed")
        self.cancel_mix()
        self.closing = True
        self.timer.stop()
        self.cancel.set()
        for job in (*self.page_jobs.values(), *self.like_jobs.values(), self.play_job, self.meta_job, self.wave_job, self.auth_job, self.mix_job):
            if job:
                job.cancel()
        self.player.close()
        if self.store:
            self.store.abort()
        self.pool.shutdown(wait=True)
        self.api.logout()
