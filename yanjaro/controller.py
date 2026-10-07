"""One serialized API worker; only safe projections reach the QML context."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from datetime import datetime, timezone
from uuid import uuid4

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices

from .api import MusicApi, safe_error


class Controller(QObject):
    changed = Signal()
    _result = Signal(str, object, str)
    _code = Signal(str, str)

    def __init__(self, player, api=None):
        super().__init__()
        self.api = api or MusicApi()
        self.player = player
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="music-api")
        self.cancel = Event()
        self.closing = False
        self.page = 0
        self.query = ""
        self.wave_station = ""
        self.wave_queue = []
        self.wave_seen = []
        self.generation = 0
        self.active_wave = None
        self.wave_started = False
        self.previous = None
        self.advance_pending = False
        self.listened = 0.0
        self.current_track = None
        self.play_session = None
        self.last_tick = time.monotonic()
        self._state = dict(busy=False, signedIn=False, message=player.error or "Войдите, чтобы открыть музыку.",
                           code="", loginUrl="", view="likes", heading="Мне нравится",
                           rows=[], more=False, current="Ничего не играет", waveActive=False,
                           playReport="События этого запуска ещё не отправлялись.")
        self._result.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        self._code.connect(self._show_code, Qt.ConnectionType.QueuedConnection)
        player.changed.connect(self.changed)
        player.failed.connect(self._error)
        player.started.connect(self._started)
        player.ended.connect(self._ended)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)

    @Property("QVariantMap", notify=changed)
    def state(self):
        return self._state | self.player.state

    def _submit(self, operation, call):
        if self._state["busy"] or self.closing:
            return False
        self._state.update(busy=True, message="Подождите…")
        self.changed.emit()

        def run():
            try:
                result = call()
                self._result.emit(operation, result, "")
            except Exception as exc:
                self._result.emit(operation, None, safe_error(exc))

        self.pool.submit(run)
        return True

    @Slot(str, object, str)
    def _completed(self, operation, result, error):
        if self.closing:
            return
        if operation == "play-report":
            self._state["playReport"] = error or "Событие прослушивания принято сервером. Обновление истории этим не подтверждено."
            self.changed.emit()
            return
        if operation == "refill":
            generation, batch = result
            if generation != self.generation:
                return
            if error:
                self._error(error)
            elif batch:
                self._append_wave(batch)
                self._state["message"] = "Следующая партия волны получена"
                self.changed.emit()
            return
        if operation == "notice":
            if error:
                self._error(error)
            return
        self._state["busy"] = False
        if operation == "login":
            self._state.update(code="", loginUrl="")
        if error:
            self._error(error)
            self._advance_if_idle()
            return
        if operation == "login":
            self._state["signedIn"] = True
            self.show("likes")
        elif operation == "logout":
            self._state.update(signedIn=False, rows=[], more=False, current="Ничего не играет",
                               playReport="События этого запуска ещё не отправлялись.",
                               message="Вы вышли. Токен удалён из памяти клиента.")
        elif operation == "wave":
            self._append_wave(result)
            self._take_wave()
        elif operation == "play":
            self.current_track = result.track
            self.listened = 0.0
            self._state.update(current=result.track.title + " · " + result.track.artist,
                               message="Загрузка полного аудио…")
            self.player.play(result)
        elif operation in ("page", "more"):
            self._state["rows"] = (self._state["rows"] if operation == "more" else []) + result.rows
            self._state.update(more=result.more, message=result.note or
                               ("Готово" if self._state["rows"] else "Ничего не найдено"))
            if operation == "more":
                self.page += 1
        self.changed.emit()
        self._advance_if_idle()

    def _advance_if_idle(self):
        if self.advance_pending and not self._state["busy"]:
            self.advance_pending = False
            self.next_wave()

    @Slot(str, str)
    def _show_code(self, url, code):
        if self.closing or self.cancel.is_set():
            return
        self._state.update(code=code, loginUrl=url, message="Подтвердите вход в браузере.")
        self.open_browser()
        self.changed.emit()

    @Slot()
    def open_browser(self):
        if self._state["loginUrl"] and not QDesktopServices.openUrl(QUrl(self._state["loginUrl"])):
            self._error("Браузер не открылся. Откройте адрес, указанный рядом с кодом.")

    @Slot()
    def login(self):
        if self._state["busy"] or self._state["signedIn"]:
            return
        self.cancel.clear()
        self._submit("login", lambda: self.api.login(self._code.emit, self.cancel))

    @Slot()
    def cancel_login(self):
        self.cancel.set()
        self._state.update(code="", loginUrl="", message="Отменяем вход…")
        self.changed.emit()

    @Slot()
    def logout(self):
        if not self._state["busy"]:
            self._leave_wave()
            self.player.stop()
            self._submit("logout", self.api.logout)

    def _page_call(self, page):
        if self._state["view"] == "stations":
            return self.api.stations()
        if self._state["view"] == "history":
            return self.api.history()
        return self.api.search(self.query, page) if self._state["view"] == "search" else self.api.likes(page)

    @Slot(str)
    def show(self, view):
        if self._state["busy"] or not self._state["signedIn"]:
            return
        headings = {"likes": "Мне нравится", "search": "Поиск", "stations": "Станции", "history": "История Яндекса"}
        if view not in headings:
            return
        self.page = 0
        self._state.update(view=view, heading=headings[view], rows=[], more=False)
        self._submit("page", lambda: self._page_call(0))

    @Slot(str)
    def search(self, query):
        if not self._state["busy"]:
            self.query = query
            self.show("search")

    @Slot()
    def more(self):
        if self._state["more"]:
            self._submit("more", lambda: self._page_call(self.page + 1))

    @Slot(str)
    def play(self, track_id):
        if self._state["busy"]:
            return
        if self._state["view"] == "stations":
            self.start_wave(track_id)
            return
        if not self.player.state["ready"]:
            self._error(self.player.error)
            return
        self._leave_wave()
        self.player.stop()
        self._submit("play", lambda: self.api.stream(track_id))

    def _tick(self):
        now = time.monotonic()
        state = self.player.state
        if self.play_session and state["loaded"] and not state["paused"] and not state["buffering"]:
            self.listened += min(now - self.last_tick, 1)
        self.last_tick = now

    def _finish_track(self, event):
        session = self.play_session
        self.play_session = None
        if session and self.listened > 0:
            track, play_id, started_at = session
            seconds, position = self.listened, self.player.state["position"]

            def report():
                try:
                    self.api.report_play(track, play_id, started_at, seconds, position)
                    self._result.emit("play-report", None, "")
                except Exception as exc:
                    self._result.emit("play-report", None, safe_error(exc))
            self.pool.submit(report)
        active = self.active_wave
        self.active_wave = None
        if not active or not self.wave_started:
            self.wave_started = False
            return
        self.wave_started = False
        station, track_id, batch = active
        seconds = self.listened
        self.previous = track_id

        def send():
            try:
                self.api.feedback(station, event, track_id, batch, seconds)
            except Exception as exc:
                self._result.emit("notice", None, safe_error(exc))
        self.pool.submit(send)

    def _leave_wave(self):
        self._finish_track("skip")
        self.generation += 1
        self.wave_station = ""
        self.wave_queue = []
        self.wave_seen = []
        self.previous = None
        self.advance_pending = False
        self._state["waveActive"] = False

    @Slot(str)
    def start_wave(self, station):
        if self._state["busy"] or not self._state["signedIn"]:
            return
        if not self.player.state["ready"]:
            self._error(self.player.error)
            return
        self._leave_wave()
        self.player.stop()
        self.wave_station = station
        self._state.update(waveActive=True)
        self._submit("wave", lambda: self.api.wave_batch(station, start=True))

    def _append_wave(self, batch):
        excluded = set(self.wave_seen) | {t.id for t, _ in self.wave_queue}
        for track in batch.tracks:
            if track.available and track.id not in excluded:
                self.wave_queue.append((track, batch.batch))
                excluded.add(track.id)

    def _take_wave(self):
        if not self.wave_station or self.closing:
            return
        if not self.wave_queue:
            self._error("В партии нет новых доступных треков. Нажмите «Следующая партия» для повторного запроса.")
            return
        track, batch = self.wave_queue.pop(0)
        self.wave_seen = (self.wave_seen + [track.id])[-100:]
        self.active_wave = (self.wave_station, track.id, batch)
        self.listened = 0.0
        self._submit("play", lambda: self.api.stream(track.id))

    @Slot()
    def next_wave(self):
        if self._state["busy"] or not self.wave_station:
            return
        self._finish_track("skip")
        self.player.stop()
        if self.wave_queue:
            self._take_wave()
        else:
            station, previous = self.wave_station, self.previous
            self._submit("wave", lambda: self.api.wave_batch(station, previous))

    @Slot()
    def _started(self):
        if self.closing:
            return
        if self.current_track and not self.play_session:
            self.play_session = (self.current_track, str(uuid4()), datetime.now(timezone.utc).isoformat())
            self.last_tick = time.monotonic()
        self._state["message"] = "Воспроизведение"
        self.changed.emit()
        if not self.active_wave or self.wave_started:
            return
        self.wave_started = True
        station, track_id, batch = self.active_wave
        previous, generation = self.previous, self.generation
        self.previous = None

        def refill():
            try:
                self.api.feedback(station, "trackStarted", track_id, batch)
                result = self.api.wave_batch(station, previous) if previous else None
                self._result.emit("refill", (generation, result), "")
            except Exception as exc:
                self._result.emit("refill", (generation, None), safe_error(exc))
        self.pool.submit(refill)

    @Slot()
    def _ended(self):
        if self.closing:
            return
        self._finish_track("trackFinished")
        if self.wave_station:
            if self._state["busy"]:
                self.advance_pending = True
            else:
                self.next_wave()

    @Slot()
    def pause(self):
        self.player.toggle_pause()

    @Slot(float)
    def seek(self, seconds):
        self.player.seek(seconds)

    @Slot(str)
    def _error(self, message):
        self._state["message"] = message
        self.changed.emit()

    def close(self):
        self._finish_track("skip")
        self.closing = True
        self.timer.stop()
        self.cancel.set()
        self.player.close()
        self.pool.shutdown(wait=True)
        self.api.logout()
