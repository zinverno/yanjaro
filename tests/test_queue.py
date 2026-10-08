"""Finite queue semantics with explicit synthetic API/engine events."""
import threading
import unittest
from unittest.mock import Mock, patch
from yanjaro.api import Track, Stream, WaveBatch
from yanjaro.controller import PlaybackController
from test_desktop import APP, until
from test_wave import StubPlayer


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.p, self.api = StubPlayer(), Mock()
        self.tracks = [Track(str(i), 'Synthetic', '', 180, True) for i in range(60)]
        self.api.stream.side_effect = lambda id, cancel=None: Stream(self.tracks[int(id)], 'https://example.test/audio')
        self.api.track_rows.side_effect = lambda ids: [self.tracks[int(id)].row() for id in ids]
        self.c = PlaybackController(self.p, self.api)
        self.c._state['signedIn'] = True
        self.c.pages['likes'].update(rows=[t.row() for t in self.tracks[:2]], ids=tuple(str(i) for i in range(60)), status='ready')

    def tearDown(self):
        self.c.close()

    def playing(self, id):
        until(lambda: self.c.play_session is not None and self.c.state['currentId'] == id)

    def test_shuffle_full_collection_restore_and_actual_previous(self):
        self.c.play('0'); self.playing('0')
        with patch('yanjaro.controller.random.shuffle', side_effect=lambda rows: rows.reverse()):
            self.c.set_shuffle(True)
        self.assertEqual(self.p.played, ['0'])
        self.assertEqual(len({r['id'] for r in self.c.queue}), 60)
        self.c.next_track(); self.playing('59')
        self.c.set_shuffle(False)
        self.assertEqual([r['id'] for r in self.c.queue[2:]], [str(i) for i in range(1,59)])
        self.c.previous_track(); self.playing('0')
        self.c.next_track(); self.playing('59')
        self.c.next_track(); self.playing('1')

    def test_repeat_one_only_on_eof_all_at_last_and_single_empty(self):
        self.c.pages['likes'].update(ids=('0','1'), rows=[t.row() for t in self.tracks[:2]])
        self.c.play('0'); self.playing('0')
        self.c.set_repeat('Track')
        self.p.ended.emit(); self.playing('0')
        self.assertEqual(self.p.played, ['0','0'])
        self.c.next_track(); self.playing('1')
        self.c.set_repeat('None')
        self.p.ended.emit(); APP.processEvents()
        self.assertEqual(self.c.state['playbackStatus'], 'stopped')
        self.c.set_repeat('Playlist')
        self.c.next_track()
        self.assertEqual(self.c.state['playbackStatus'], 'stopped')
        self.c.play_resume(); self.playing('0')
        self.c.pages['likes'].update(ids=('0',), rows=[self.tracks[0].row()])
        self.c.play_collection(False); self.playing('0')
        self.p.ended.emit(); self.playing('0')
        self.assertEqual(len(self.c.queue), 1)
        self.c.queue=[]; self.c.queue_index=-1
        self.c.next_track()  # No indexing an empty queue.

    def test_duplicate_selection_resume_and_pause_during_network_load(self):
        gate, started = threading.Event(), threading.Event()
        def stream(id, cancel=None):
            started.set(); gate.wait(2)
            return Stream(self.tracks[int(id)], 'https://example.test/audio')
        self.api.stream.side_effect = stream
        try:
            self.c.play('0'); until(started.is_set)
            self.c.play('0'); self.c.pause()
            gate.set(); self.playing('0')
            self.assertEqual(self.api.stream.call_count, 1)
            self.assertTrue(self.p.state['paused'])
            self.p.state['position']=45
            self.c.play('0')
            self.assertFalse(self.p.state['paused'])
            self.assertEqual(self.p.state['position'],45)
            self.c.play('0')
            self.assertEqual(self.p.played,['0'])
            self.c.pause(); self.c.next_track(); self.playing('1')
            self.assertTrue(self.p.state['paused'])  # Shared MPRIS transport preserves pause.
            self.c.play('2'); self.playing('2')
            self.assertFalse(self.p.state['paused'])
        finally:
            gate.set()

    def test_radio_disables_modes_stop_rejects_pending_batch_and_preserves_preferences(self):
        self.c.play('0'); self.playing('0')
        self.c.set_repeat('Track'); self.c.set_shuffle(True)
        self.api.wave_batch.return_value = WaveBatch('station','one',self.tracks[:4])
        self.c.start_wave('station')
        self.playing('0')
        self.assertFalse(self.c.state['finiteQueue'])
        self.assertEqual(self.c.state['repeatMode'],'None')
        self.assertFalse(self.c.state['shuffle'])
        self.c.set_repeat('Playlist'); self.c.set_shuffle(False)
        old=self.c.generation
        self.c.stop()
        self.c._completed('wave',(old,WaveBatch('station','late',self.tracks[4:8])), '')
        self.assertFalse(self.p.state['loaded'])
        self.c.play('9'); self.playing('9')
        self.assertEqual(self.c.state['repeatMode'],'Track')
        self.assertTrue(self.c.state['shuffle'])
        events=[tuple(call.args[:4]) for call in self.api.feedback.call_args_list]
        self.assertEqual(events.count(('station','skip','0','one')),1)

    def test_switch_cancels_old_api_retry_and_new_loading_pause_survives(self):
        from yanjaro.api import MusicApi
        from yandex_music.exceptions import TimedOutError
        from test_api import track
        client = Mock()
        api = MusicApi(client); api.authenticated = True
        self.c.api = api
        self.c.pages['likes'].update(ids=('0','1'), rows=[t.row() for t in self.tracks[:2]])
        client.tracks.side_effect = lambda ids: [track(id) for id in ids]
        full = Mock(preview=False, codec='mp3', bitrate_in_kbps=192)
        full.get_direct_link.return_value = 'https://example.test/audio'
        gate, started = threading.Event(), threading.Event()
        def variants(id):
            if id == '0':
                started.set(); gate.wait(2)
                raise TimedOutError()
            return [full]
        client.tracks_download_info.side_effect = variants
        try:
            self.c.play('0'); until(started.is_set)
            self.c.play('1'); self.c.pause()
            gate.set(); self.playing('1')
            self.assertEqual([call.args[0] for call in client.tracks_download_info.call_args_list], ['0','1'])
            self.assertEqual(self.p.played, ['1'])
            self.assertTrue(self.p.state['paused'])
            self.assertFalse(self.c.state['playerError'])
        finally:
            gate.set()
