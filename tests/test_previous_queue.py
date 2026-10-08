"""Previous can walk backwards from a fresh middle-of-collection selection.

Synthetic audio/API only. The installed package and account need separate checks.
"""
import threading
import unittest
import tempfile
import wave
from unittest.mock import Mock, patch
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from jeepney import DBusAddress, HeaderFields, new_method_call
from yanjaro.mpris import Mpris, PLAYER, PATH, PROPERTIES
from test_mpris import wire

from yanjaro.api import Stream, Track
from yanjaro.controller import PlaybackController
from yanjaro.player import Player
from test_desktop import APP, until
from test_wave import StubPlayer


class QueuePreviousFallbackTests(unittest.TestCase):
    def setUp(self):
        self.player, self.api = StubPlayer(), Mock()
        self.tracks = [Track(str(i), f'Track {i}', 'Artist', 180, True) for i in range(60)]
        self.api.stream.side_effect = lambda track_id, cancel=None: Stream(
            self.tracks[int(track_id.split(':', 1)[0])], 'https://example.test/audio')
        self.api.track_rows.side_effect = lambda ids: [
            self.tracks[int(track_id.split(':', 1)[0])].row() for track_id in ids]
        self.c = PlaybackController(self.player, self.api)
        self.c._state['signedIn'] = True
        self.c.pages['likes'].update(
            rows=[t.row() for t in self.tracks[:2]],
            ids=tuple(str(i) for i in range(60)), status='ready')

    def tearDown(self):
        self.c.close()

    def playing(self, track_id):
        until(lambda: self.c.play_session is not None
              and self.c.state['currentId'] == str(track_id))

    def test_previous_backtracks_from_unloaded_middle_then_next_returns(self):
        self.c.play('45')
        self.playing(45)
        self.assertEqual(self.c.queue_index, 45)
        self.assertEqual(len(self.c.queue), 60)
        self.assertTrue(self.c.state['canPrevious'])
        for expected in (44, 43):
            self.c.previous_track()
            self.playing(expected)
        self.assertEqual(self.c.queue_history, ['43', '44', '45'])
        for expected in (44, 45):
            self.c.next_track()
            self.playing(expected)
        self.assertEqual(len(self.c.queue), 60)
        self.assertEqual([r['id'].split(':')[0] for r in self.c.queue], [str(i) for i in range(60)])
        for expected in range(44, -1, -1):
            self.c.previous_track(); self.playing(expected)
        self.assertFalse(self.c.state['canPrevious'])
        self.assertEqual(len(self.c.queue), 60)

    def test_real_playback_history_takes_priority_before_queue_fallback(self):
        self.c.play('45'); self.playing(45)
        self.c.jump_queue(52); self.playing(52)  # History must beat queue predecessor 51.
        self.c.previous_track(); self.playing(45)
        self.c.previous_track(); self.playing(44)
        self.c.next_track(); self.playing(45)
        self.c.next_track(); self.playing(52)
        self.assertEqual([r['id'] for r in self.c.queue[44:47]], ['44', '45', '46'])

    def test_first_item_and_unavailable_predecessors(self):
        self.c.play('0'); self.playing(0)
        self.assertFalse(self.c.state['canPrevious'])
        self.c.previous_track()
        self.assertEqual(self.player.played, ['0'])
        # Existing metadata can mark tracks unavailable; never select those.
        self.c.pages['likes'].update(
            rows=[Track('0', 'Zero', '', 180, False).row(),
                  Track('1', 'One', '', 180, False).row(),
                  self.tracks[2].row()],
            ids=('0', '1', '2'), status='ready')
        self.c.play('2'); self.playing(2)
        self.assertFalse(self.c.state['canPrevious'])
        self.c.previous_track()
        self.assertEqual(self.c.state['currentId'], '2')

    def test_rapid_previous_during_initial_load_walks_in_one_direction(self):
        started, release = threading.Event(), threading.Event()
        def delayed(track_id, cancel=None):
            if track_id == '45':
                started.set()
                release.wait(2)
            return Stream(self.tracks[int(track_id)], 'https://example.test/audio')
        self.api.stream.side_effect = delayed
        try:
            self.c.play('45')
            until(started.is_set)
            self.c.previous_track()
            self.c.previous_track()
            release.set()
            self.playing(43)
            self.assertEqual(self.c.queue_history, ['43', '44', '45'])
            self.assertEqual(self.player.played, ['43'])
        finally:
            release.set()

    def test_rapid_history_previous_and_next_use_pending_selection(self):
        self.c.play('45'); self.playing(45)
        self.c.next_track(); self.playing(46)
        self.c.next_track(); self.playing(47)
        entered, release = threading.Event(), threading.Event()
        def stream(track_id, cancel=None):
            if track_id == '46': entered.set(); release.wait(2)
            return Stream(self.tracks[int(track_id)], 'https://example.test/audio')
        self.api.stream.side_effect = stream
        try:
            self.c.previous_track(); until(entered.is_set)
            self.c.previous_track()
            self.assertEqual(self.c.state['currentId'], '45')
            release.set(); self.playing(45)
            self.assertEqual(self.player.played, ['45', '46', '47', '45'])
            entered.clear(); release.clear()
            self.c.next_track(); until(entered.is_set)
            self.c.next_track()
            self.assertEqual(self.c.state['currentId'], '47')
            self.c.next_track()  # Leaving forward history must not retain a stale target.
            release.set(); self.playing(48)
            self.assertEqual(self.c.queue_history, ['45', '46', '47', '48'])
            self.assertEqual(self.player.played, ['45', '46', '47', '45', '48'])
            self.c.previous_track(); self.playing(47)
        finally:
            release.set()

    def test_explicit_queue_jump_cancels_pending_history_target(self):
        self.c.play('45'); self.playing(45)
        self.c.next_track(); self.playing(46)
        self.c.next_track(); self.playing(47)
        entered, release = threading.Event(), threading.Event()
        def stream(track_id, cancel=None):
            if track_id == '46': entered.set(); release.wait(2)
            return Stream(self.tracks[int(track_id)], 'https://example.test/audio')
        self.api.stream.side_effect = stream
        try:
            self.c.previous_track(); until(entered.is_set)
            self.c.jump_queue(20)
            release.set(); self.playing(20)
            self.assertEqual(self.c.queue_history, ['45', '46', '47', '20'])
            self.c.previous_track(); self.playing(47)
        finally:
            release.set()

    def test_pending_history_at_queue_end_keeps_next_capability(self):
        self.c.play('59'); self.playing(59)
        self.c.jump_queue(45); self.playing(45)
        entered, release = threading.Event(), threading.Event()
        def stream(track_id, cancel=None):
            if track_id == '59': entered.set(); release.wait(2)
            return Stream(self.tracks[int(track_id)], 'https://example.test/audio')
        self.api.stream.side_effect = stream
        try:
            self.c.previous_track(); until(entered.is_set)
            self.assertTrue(self.c.state['canNext'])  # Pending history target 59 has forward entry 45.
            self.c.next_track()
            release.set(); self.playing(45)
            self.assertEqual(self.player.played, ['59', '45', '45'])
        finally:
            release.set()

    def test_fallback_skips_unavailable_and_preserves_shuffle_repeat_and_stop(self):
        self.c.pages['likes']['rows'] = [t.row() for t in self.tracks]
        self.c.pages['likes']['rows'][44]['available'] = False
        self.c.play('45'); self.playing(45)
        with patch('yanjaro.controller.random.shuffle', side_effect=lambda rows: rows.reverse()):
            self.c.set_shuffle(True)
        order = [r['id'] for r in self.c.queue]
        self.c.set_repeat('Track')
        self.c.previous_track(); self.playing(43)
        self.assertEqual([r['id'] for r in self.c.queue], order)
        self.player.ended.emit(); self.playing(43)
        self.assertEqual(self.player.played[-2:], ['43', '43'])
        self.c.next_track(); self.playing(45)  # Repeat-one only intercepts natural EOF.
        self.c.set_shuffle(False)
        self.assertEqual([r['id'] for r in self.c.queue], [str(i) for i in range(60)])
        self.c.stop(); count = len(self.player.played)
        self.c.previous_track()
        self.assertEqual(self.c.state['currentId'], '43')
        self.assertEqual(self.c.state['playbackStatus'], 'stopped')
        self.assertEqual(len(self.player.played), count)

    def test_qml_and_mpris_share_previous_state_and_preserve_pause(self):
        sent = []
        bus = Mock(); bus.send.side_effect = lambda message: sent.append(wire(message))
        service = Mpris(self.c, Mock(), Mock(), connection=bus)
        engine = QQmlApplicationEngine()
        engine.setInitialProperties({'music': self.c})
        engine.load(Path(__file__).parents[1] / 'yanjaro/Main.qml')
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        def call(interface, method, signature='', args=()):
            msg = new_method_call(DBusAddress(PATH, bus_name='org.mpris.MediaPlayer2.yanjaro', interface=interface), method, signature, args)
            msg.header.serial = 7; msg.header.fields[HeaderFields.sender] = ':1.9'
            service.handle(wire(msg))
            return sent[-1]
        try:
            QTest.qWait(60)
            button = window.findChild(QObject, 'previousButton')
            self.assertFalse(button.isEnabled())
            self.c.play('45'); self.playing(45)
            self.assertTrue(button.isEnabled())
            self.assertEqual(call(PROPERTIES, 'GetAll', 's', (PLAYER,)).body[0]['CanGoPrevious'], ('b', True))
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier,
                            button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint())
            self.playing(44)
            self.c.pause()
            call(PLAYER, 'Previous'); self.playing(43)
            self.assertTrue(self.player.state['paused'])
            call(PLAYER, 'Next'); self.playing(44)
            self.assertTrue(self.player.state['paused'])
            self.c.play('0'); self.playing(0)
            self.assertFalse(button.isEnabled())
            self.assertEqual(call(PROPERTIES, 'GetAll', 's', (PLAYER,)).body[0]['CanGoPrevious'], ('b', False))
            self.assertTrue(any(msg.body[0] == PLAYER and msg.body[1].get('CanGoPrevious') == ('b', False)
                                for msg in sent if msg.header.fields.get(HeaderFields.member) == 'PropertiesChanged'))
            self.c.wave_station = 'station'; self.c.changed.emit()
            played = list(self.player.played)
            call(PLAYER, 'Previous'); self.c.previous_track()
            self.assertFalse(button.isEnabled())
            self.assertEqual(self.player.played, played)
            self.api.feedback.assert_not_called()
        finally:
            window.close(); service.close(); del engine

    def test_real_libmpv_previous_next_and_loading_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'none'))
                wav.writeframes(b'\0\0' * 16000 * 8)
            player, api = Player(audio_output='null'), Mock()
            self.assertTrue(player.state['ready'], player.error)
            tracks = [Track(str(i), 'Synthetic', '', 8, True) for i in range(4)]
            api.stream.side_effect = lambda track_id, cancel=None: Stream(tracks[int(track_id)], str(path))
            c = PlaybackController(player, api)
            c.pages['likes'].update(rows=[t.row() for t in tracks], ids=tuple(str(i) for i in range(4)), status='ready')
            engine = QQmlApplicationEngine(); engine.setInitialProperties({'music': c})
            engine.load(Path(__file__).parents[1] / 'yanjaro/Main.qml')
            self.assertTrue(engine.rootObjects())
            window = engine.rootObjects()[0]
            try:
                c.play('3')
                until(lambda: c.play_session is not None and player.state['position'] > .1)
                self.assertTrue(window.findChild(QObject, 'previousButton').isEnabled())
                c.previous_track(); c.previous_track(); c.set_paused(True)
                until(lambda: c.play_session is not None and c.state['currentId'] == '1' and player.state['paused'])
                self.assertEqual(c.queue_history, ['1', '2', '3'])
                self.assertTrue(player.engine.pause)
                self.assertEqual(window.findChild(QObject, 'pauseButton').property('symbol'), 'play')
                c.next_track()
                until(lambda: c.play_session is not None and c.state['currentId'] == '2')
                self.assertTrue(player.state['paused'])
                c.play_resume(); until(lambda: not player.state['paused'] and player.state['position'] > .1)
                self.assertEqual(window.findChild(QObject, 'pauseButton').property('symbol'), 'pause')
                self.assertEqual([r['id'] for r in c.queue], ['0', '1', '2', '3'])
            finally:
                window.close(); c.close(); del engine


if __name__ == '__main__':
    unittest.main()
