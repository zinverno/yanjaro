"""Synthetic API contracts, never account evidence."""
import threading
import unittest
from unittest.mock import Mock, patch

from yanjaro.api import Page, Stream, Track, WaveBatch
from yanjaro.controller import PlaybackController
from test_desktop import until, APP
from test_wave import StubPlayer


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.api, self.player = Mock(), StubPlayer()
        self.tracks = [Track(str(i), f'Test track {i}', 'Test artist', 180, True) for i in range(12)]
        self.api.stream.side_effect = lambda id: Stream(self.tracks[int(id.split(':')[0])], 'https://example.test/audio')
        self.api.track_rows.side_effect = lambda ids: [self.tracks[int(id)].row() for id in ids]
        self.c = PlaybackController(self.player, self.api)
        self.c._state['signedIn'] = True

    def tearDown(self):
        self.c.close()

    def test_slow_search_cannot_replace_new_results_or_block_navigation(self):
        started, release = threading.Event(), threading.Event()
        def search(query, page):
            if query == 'old':
                started.set()
                release.wait(2)
            return Page([self.tracks[0 if query == 'old' else 1].row()])
        self.api.search.side_effect = search
        self.api.stations.return_value = Page([])
        try:
            self.c.search('old')
            until(started.is_set)
            self.c.search('new')
            self.assertEqual(self.c.state['query'], 'new')
            self.assertEqual(self.c.content['rows'], [])
            self.c.show('stations')
            self.assertEqual(self.c.state['view'], 'stations')
            release.set()
            until(lambda: self.c.pages['search']['status'] == 'ready')
            self.assertEqual(self.c.pages['search']['rows'][0]['id'], '1')
            self.assertEqual(self.c.state['view'], 'stations')
            self.c.show('search')
            self.assertEqual(self.c.content['rows'][0]['id'], '1')
        finally:
            release.set()

    def test_likes_queue_includes_whole_collection_and_navigation_preserves_it(self):
        self.api.likes.return_value = Page([t.row() for t in self.tracks[:2]], more=True,
                                          total=12, ids=tuple(str(i) for i in range(12)))
        self.api.stations.return_value = Page([])
        self.c.show('likes')
        until(lambda: self.c.state['pageStatus'] == 'ready')
        self.c.save_scroll(123)
        self.c.play('1')
        until(lambda: self.c.play_session is not None)
        self.assertEqual(len(self.c.queue), 12)
        self.assertEqual(self.c.queue_index, 1)
        queue_ids = [r['id'] for r in self.c.queue]
        self.c.show('stations')
        until(lambda: self.c.state['pageStatus'] == 'ready')
        self.c.show('likes')
        self.assertEqual([r['id'] for r in self.c.queue], queue_ids)
        self.assertEqual(self.c.state['pageScroll'], 123)
        self.assertTrue(self.player.state['loaded'])
        self.c.next_track()
        until(lambda: self.player.played[-1] == '2')
        self.c.previous_track()
        until(lambda: self.player.played[-1] == '1')
        with patch('yanjaro.controller.random.shuffle', side_effect=lambda rows: rows.reverse()):
            self.c.play_collection(True)
        until(lambda: self.player.played[-1] == '11')
        self.assertEqual(len(self.c.queue), 12)

    def test_pagination_deduplicates_and_has_one_request_with_retry(self):
        gate = threading.Event()
        def likes(page):
            if page:
                gate.wait(2)
                return Page([self.tracks[0].row(), self.tracks[1].row()], total=2)
            return Page([self.tracks[0].row()], more=True, total=2)
        self.api.likes.side_effect = likes
        self.c.show('likes')
        until(lambda: self.c.state['pageStatus'] == 'ready')
        try:
            self.c.more()
            self.c.more()
            self.c.more()
            gate.set()
            until(lambda: self.c.state['pageStatus'] == 'ready')
            self.assertEqual(self.api.likes.call_count, 2)
            self.assertEqual([r['id'] for r in self.c.content['rows']], ['0', '1'])
        finally:
            gate.set()

    def test_late_station_and_stream_cannot_take_over_search_playback(self):
        gate, started = threading.Event(), threading.Event()
        def batch(*args, **kwargs):
            started.set()
            gate.wait(2)
            return WaveBatch('old', 'batch', self.tracks[:3])
        self.api.wave_batch.side_effect = batch
        self.c.start_wave('old')
        try:
            until(started.is_set)
            self.c.pages['search'].update(rows=[self.tracks[8].row()], status='ready')
            self.c.query = 'test'
            self.c.show('search')
            self.c.play('8')
            gate.set()
            until(lambda: self.player.played == ['8'])
            self.assertEqual(self.c.wave_queue, [])
            self.assertEqual(self.c.state['source'], 'Поиск: test')
            self.c._completed('play', ((self.c.generation - 1, self.c.play_revision),
                              Stream(self.tracks[0], 'https://example.test/old')), '')
            self.assertEqual(self.player.played, ['8'])
        finally:
            gate.set()

    def test_wave_crosses_batch_boundary_with_correct_feedback_and_bounded_failure(self):
        self.api.wave_batch.side_effect = [WaveBatch('station', 'one', self.tracks[:2]),
            WaveBatch('station', 'two', self.tracks[2:6]), RuntimeError('SECRET'),
            WaveBatch('station', 'three', self.tracks[6:])]
        self.c.start_wave('station')
        until(lambda: self.c.wave_started and len(self.c.wave_queue) == 5)
        self.c.listened = 3
        self.player.ended.emit()
        until(lambda: self.player.played[-1] == '1' and self.c.wave_started)
        self.player.ended.emit()
        until(lambda: self.player.played[-1] == '2' and self.c.wave_started)
        self.assertEqual(self.c.active_wave[2], 'two')
        self.c.next_track()
        until(lambda: bool(self.c.state['stationError']))
        self.assertNotIn('SECRET', self.c.state['stationError'])
        attempts = self.api.wave_batch.call_count
        self.c.next_track()
        until(lambda: self.player.played[-1] == '4')
        self.c.next_track()
        until(lambda: self.player.played[-1] == '5')
        self.player.ended.emit()
        APP.processEvents()
        self.assertEqual(self.api.wave_batch.call_count, attempts)
        self.assertFalse(self.c.state['loading'])
        self.c.retry_station()
        until(lambda: self.player.played[-1] == '6')
        self.assertEqual(self.c.active_wave[2], 'three')
        events = [(c.args[1], c.args[2], c.args[3]) for c in self.api.feedback.call_args_list]
        self.assertIn(('trackFinished', '0', 'one'), events)
        self.assertIn(('trackFinished', '1', 'one'), events)
        self.assertIn(('skip', '2', 'two'), events)

    def test_page_error_does_not_stop_or_change_the_playing_queue(self):
        self.c.play('2')
        until(lambda: self.c.play_session is not None)
        self.api.stations.side_effect = RuntimeError('SECRET')
        self.c.show('stations')
        until(lambda: self.c.state['pageStatus'] == 'error')
        self.assertTrue(self.player.state['loaded'])
        self.assertEqual(self.c.state['currentId'], '2')
        self.assertNotIn('SECRET', self.c.state['pageError'])
        self.api.stations.side_effect = None
        self.api.stations.return_value = Page([])
        self.c.retry_page()
        until(lambda: self.c.state['pageStatus'] == 'ready')

    def test_repeating_same_search_does_not_extend_previous_queue(self):
        self.api.search.side_effect = [Page([self.tracks[0].row()], more=True),
                                      Page([self.tracks[1].row()], more=True),
                                      Page([self.tracks[2].row()])]
        self.c.search('same query')
        until(lambda: self.c.state['pageStatus'] == 'ready')
        self.c.play('0')
        until(lambda: self.c.play_session is not None)
        self.c.search('same query')
        until(lambda: self.c.state['pageStatus'] == 'ready')
        self.c.more()
        until(lambda: self.c.state['pageStatus'] == 'ready')
        self.assertEqual([r['id'] for r in self.c.content['rows']], ['1', '2'])
        self.assertEqual([r['id'] for r in self.c.queue], ['0'])

    def test_unavailable_collection_cannot_leave_previous_track_playing(self):
        self.c.play('2')
        until(lambda: self.c.play_session is not None)
        self.c.pages['likes'].update(rows=[dict(self.tracks[0].row(), available=False)],
                                     ids=('0',), status='ready')
        self.c.play_collection(False)
        self.assertFalse(self.player.state['loaded'])
        self.assertEqual(self.c.state['currentId'], '')
        self.assertIn('нет доступных', self.c.state['playerError'])
