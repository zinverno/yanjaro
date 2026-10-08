"""libmpv audio engine. Qt signals marshal its event thread onto the UI thread."""

from PySide6.QtCore import QObject, Signal, Slot, Qt


class Player(QObject):
    changed = Signal()
    started = Signal()
    ended = Signal()
    failed = Signal(str)
    _event = Signal(str, object)

    def __init__(self, audio_output=None):
        super().__init__()
        self.state = dict(ready=False, loaded=False, paused=True, position=0.0,
                          duration=0.0, seekable=False, buffering=False, volume=60.0, muted=False)
        self.engine = None
        self.error = ""
        self.expected_duration = 0
        self._event.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        try:
            import mpv
            options = dict(vo="null", video=False, config=False, load_scripts=False,
                           ytdl=False, terminal=False, msg_level="all=no",
                           audio_display="no", input_default_bindings=False,
                           resume_playback=False, save_position_on_quit=False,
                           cache_on_disk=False, network_timeout=10, volume=60)
            if audio_output:
                options["ao"] = audio_output
            self.engine = mpv.MPV(**options)
            for name in ("time-pos", "duration", "pause", "seekable", "paused-for-cache", "volume", "mute"):
                self.engine.observe_property(name, lambda name, value: self._event.emit(name, value))

            @self.engine.event_callback("file-loaded", "end-file")
            def event(event):
                if event.event_id.value == mpv.MpvEventID.FILE_LOADED:
                    self._event.emit("loaded", None)
                elif event.data.reason in (0, 4):  # EOF or error; stop/replacement is not EOF.
                    self._event.emit("ended" if event.data.reason == 0 else "error", None)

            self.state["ready"] = True
        except (ImportError, OSError, RuntimeError, ValueError):
            self.error = "Не удалось загрузить libmpv. Проверьте установку mpv и его библиотек."

    @Slot(str, object)
    def _receive(self, name, value):
        fields = {"time-pos": "position", "duration": "duration", "pause": "paused",
                  "seekable": "seekable", "paused-for-cache": "buffering", "volume": "volume", "mute": "muted"}
        if name in fields and value is not None:
            self.state[fields[name]] = value
        elif name == "loaded":
            self.state["loaded"] = True
            self.started.emit()
        elif name in ("ended", "error"):
            self.state["loaded"] = False
            self.state["paused"] = True
            if name == "ended":
                self.ended.emit()
            else:
                self.failed.emit("Аудио не воспроизведено. Нажмите трек ещё раз, чтобы получить новую ссылку.")
        if name == "duration" and value and self.expected_duration:
            if value < self.expected_duration * 0.95 and self.expected_duration - value > 5:
                self.stop()
                self.failed.emit("Полученное аудио короче полного трека. Воспроизведение остановлено.")
        self.changed.emit()

    def _command(self, *args):
        if not self.engine:
            self.failed.emit(self.error)
            return

        def done(error, _result):
            if error:
                self._event.emit("error", None)

        try:
            self.engine.command_async(*args, callback=done)
        except (RuntimeError, ValueError):
            self.failed.emit("Команда аудиодвижка не выполнена.")

    def play(self, stream):
        self.expected_duration = stream.track.duration
        self.state.update(loaded=False, position=0.0, duration=0.0, seekable=False)
        self._command("set", "pause", "no")
        self._command("loadfile", stream.url, "replace")
        self.changed.emit()

    @Slot()
    def toggle_pause(self):
        if self.state["loaded"]:
            self._command("cycle", "pause")

    @Slot(float)
    def seek(self, seconds):
        if self.state["loaded"] and self.state["seekable"]:
            self._command("seek", max(0, min(seconds, self.state["duration"])), "absolute+exact")

    def stop(self):
        self.expected_duration = 0
        self._command("stop")
        self.state.update(loaded=False, paused=True, position=0.0, duration=0.0, seekable=False)
        self.changed.emit()

    def set_volume(self, value):
        self._command("set", "volume", max(0, min(value, 100)))

    def toggle_mute(self):
        self._command("cycle", "mute")

    def close(self):
        if self.engine:
            self.engine.terminate()
            self.engine = None
