"""libmpv audio engine. Only queued Qt slots mutate observed state.

File lifecycle events carry mpv playlist IDs, independent from API request generations.
No audio URLs or raw engine errors cross the public signals.
"""
from PySide6.QtCore import QObject, Signal, Slot, Qt


class Player(QObject):
    changed = Signal()
    started = Signal()
    ended = Signal()
    failed = Signal(str)
    seeked = Signal(float)
    _event = Signal(str, object)
    FIELDS = {'time-pos': 'position', 'duration': 'duration', 'pause': 'paused',
              'seekable': 'seekable', 'paused-for-cache': 'buffering',
              'seeking': 'seeking',
              'volume': 'volume', 'mute': 'muted'}

    def __init__(self, audio_output=None):
        super().__init__()
        self.state = dict(ready=False, loaded=False, paused=True, position=0.0,
                          duration=0.0, seekable=False, seeking=False, buffering=False, volume=60.0, muted=False)
        self.engine = None
        self.error = ''
        self.expected_duration = 0
        self.revision = 0
        self.entry = None
        self._thread_entry = None  # Owned exclusively by mpv's event thread.
        self._awaiting = False
        self._pending = []
        self._seeking = False
        self._event.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        try:
            import mpv
            options = dict(vo='null', video=False, config=False, load_scripts=False,
                           ytdl=False, terminal=False, msg_level='all=no',
                           audio_display='no', input_default_bindings=False,
                           resume_playback=False, save_position_on_quit=False,
                           cache_on_disk=False, network_timeout=10, volume=60)
            if audio_output:
                options['ao'] = audio_output
            self.engine = mpv.MPV(**options)
            for name in self.FIELDS:
                self.engine.observe_property(name, lambda name, value:
                    self._event.emit(name, (self._thread_entry, value)))

            @self.engine.event_callback('start-file', 'file-loaded', 'end-file', 'playback-restart')
            def event(event):
                kind = event.event_id.value
                if kind == mpv.MpvEventID.START_FILE:
                    self._thread_entry = event.data.playlist_entry_id
                elif kind == mpv.MpvEventID.FILE_LOADED:
                    # Observe_property only reports changes. Take an initial snapshot even
                    # when pause remains false across stop/load (the rc1 regression).
                    snapshot = {}
                    for name, field in self.FIELDS.items():
                        try:
                            value = self.engine._get_property(name)
                            if value is not None:
                                snapshot[field] = value
                        except (RuntimeError, ValueError, AttributeError):
                            pass
                    self._event.emit('loaded', (self._thread_entry, snapshot))
                elif kind == mpv.MpvEventID.END_FILE and event.data.reason in (0, 4):
                    self._event.emit('ended' if event.data.reason == 0 else 'error',
                                     (event.data.playlist_entry_id, None))
                elif kind == mpv.MpvEventID.PLAYBACK_RESTART:
                    self._event.emit('restart', (self._thread_entry, self.engine.time_pos))
            self.state['ready'] = True
        except (ImportError, OSError, RuntimeError, ValueError):
            self.error = 'Не удалось загрузить libmpv. Проверьте установку mpv и его библиотек.'

    @Slot(str, object)
    def _receive(self, name, payload):
        entry, value = payload
        if name == 'accepted':
            if entry != self.revision:
                return
            self._awaiting = False
            if not isinstance(value, dict) or 'playlist_entry_id' not in value:
                self._failure('Аудиодвижок не подтвердил файл. Требуется совместимый mpv 0.41 или новее.')
                return
            self.entry = value['playlist_entry_id']
            pending, self._pending = self._pending, []
            for event in pending:
                self._receive(*event)
            return
        if name == 'command-error':
            if entry == self.revision:
                self._failure('Команда аудиодвижка не выполнена.')
            return
        global_property = name in ('pause', 'volume', 'mute')
        if not global_property:
            if self._awaiting:
                self._pending = (self._pending + [(name, payload)])[-64:]
                return
            if entry != self.entry or self.entry is None:
                return
        if name in self.FIELDS and value is not None:
            self.state[self.FIELDS[name]] = value
        elif name == 'loaded':
            if self.state['loaded']:
                return
            self.state.update(value, loaded=True)
            if not self._full_duration():
                return
            self.started.emit()
        elif name in ('ended', 'error'):
            self.entry = None
            self.state.update(loaded=False, buffering=False, seekable=False)
            if name == 'ended':
                self.ended.emit()
            else:
                self._failure('Аудио не воспроизведено. Повторите запуск, чтобы получить новую ссылку.')
        elif name == 'restart' and self._seeking and value is not None:
            self._seeking = False
            self.state['position'] = value
            self.seeked.emit(float(value))
        if name == 'duration' and not self._full_duration():
            return
        self.changed.emit()

    def _full_duration(self):
        value = self.state['duration']
        if value and self.expected_duration and value < self.expected_duration * .95 and self.expected_duration - value > 5:
            self.stop()
            self._failure('Полученное аудио короче полного трека. Воспроизведение остановлено.')
            return False
        return True

    def _failure(self, message):
        self._awaiting = False
        self._pending = []
        self.entry = None
        self.state.update(loaded=False, buffering=False, seekable=False)
        self.failed.emit(message)
        self.changed.emit()

    def _command(self, *args, accepted=False):
        if not self.engine:
            self.failed.emit(self.error)
            return
        revision = self.revision
        def done(error, result):
            if error:
                self._event.emit('command-error', (revision, None))
            elif accepted:
                self._event.emit('accepted', (revision, result))
        try:
            self.engine.command_async(*args, callback=done)
        except (RuntimeError, ValueError):
            self._event.emit('command-error', (revision, None))

    def play(self, stream, paused=False):
        self.revision += 1
        self.entry = None
        self._pending = []
        self._awaiting = True
        self._seeking = False
        self.expected_duration = stream.track.duration
        self.state.update(loaded=False, position=0.0, duration=0.0, seekable=False, buffering=False)
        self.set_pause(paused)
        self._command('loadfile', stream.url, 'replace', accepted=True)
        self.changed.emit()

    def set_pause(self, paused):
        self._command('set', 'pause', 'yes' if paused else 'no')

    @Slot()
    def toggle_pause(self):
        if self.state['loaded']:
            self._command('cycle', 'pause')

    @Slot(float)
    def seek(self, seconds):
        if self.state['loaded'] and self.state['seekable']:
            self._seeking = True
            self._command('seek', max(0, min(seconds, self.state['duration'])), 'absolute+exact')

    def stop(self):
        self.revision += 1
        self.entry = None
        self._awaiting = False
        self._pending = []
        self._seeking = False
        self.expected_duration = 0
        self._command('stop')
        # Stop is not a change of mpv's pause property; keep its observed value.
        self.state.update(loaded=False, position=0.0, duration=0.0, seekable=False, buffering=False)
        self.changed.emit()

    def set_volume(self, value):
        self._command('set', 'volume', max(0, min(value, 100)))

    def toggle_mute(self):
        self._command('cycle', 'mute')

    def close(self):
        self.revision += 1
        self.entry = None
        if self.engine:
            self.engine.terminate()
            self.engine = None
