import unittest
from unittest.mock import Mock

from PySide6.QtCore import QObject, Signal, QTimer

from yanjaro.api import Page, Stream, Track, WaveBatch
from yanjaro.controller import PlaybackController
from test_desktop import until


class StubPlayer(QObject):
    changed = Signal()
    started = Signal()
    ended = Signal()
    failed = Signal(str)
    seeked = Signal(float)

    def __init__(self):
        super().__init__()
        self.error = ""
        self.state = dict(ready=True, loaded=False, paused=True, buffering=False,
                          position=0.0, duration=180.0, seekable=True, volume=60.0, muted=False)
        self.played = []
        self.ended.connect(self._on_ended)

    def _on_ended(self):
        self.state.update(loaded=False, paused=True)

    def play(self, stream, paused=False):
        self.played.append(stream.track.id)
        self.state.update(loaded=True, paused=paused)
        QTimer.singleShot(0, self.started.emit)

    def set_pause(self, paused):
        self.state["paused"] = paused
        self.changed.emit()

    def stop(self):
        self.state.update(loaded=False, paused=True)

    def close(self):
        pass


class WaveTests(unittest.TestCase):
    def test_regular_track_reports_once_on_eof_with_actual_listening_time(self):
        api, player = Mock(), StubPlayer()
        track = Track("1", "Synthetic", "", 180, True, "2")
        api.stream.return_value = Stream(track, "https://example.test/private")
        c = PlaybackController(player, api)
        try:
            c.play("1")
            until(lambda: c.play_session is not None)
            c.listened = 12.5
            player.state["position"] = 150
            player.ended.emit()
            until(lambda: "принято сервером" in c.state["playReport"])
            self.assertEqual(api.report_play.call_args.args[0], track)
            self.assertAlmostEqual(api.report_play.call_args.args[3], 12.5, delta=.05)
            self.assertEqual(api.report_play.call_args.args[4], 150)
            player.ended.emit()
            self.assertEqual(api.report_play.call_count, 1)
            api.feedback.assert_not_called()
        finally:
            c.close()

    def test_wave_start_next_batch_feedback_dedup_and_history_during_playback(self):
        api, player = Mock(), StubPlayer()
        tracks = [Track(str(i), "Synthetic", "", 180, True) for i in range(4)]
        api.wave_batch.side_effect = [WaveBatch("user:onyourwave", "first", tracks[:2]),
                                      WaveBatch("user:onyourwave", "second", tracks),
                                      WaveBatch("user:onyourwave", "second", tracks)]
        api.stream.side_effect = lambda id, cancel=None: Stream(tracks[int(id)], "https://example.test/private")
        api.history.return_value = Page([])
        c = PlaybackController(player, api)
        c._state["signedIn"] = True
        try:
            c.start_wave("user:onyourwave")
            until(lambda: c.wave_started and not c.state["busy"])
            self.assertEqual(player.played, ["0"])
            c.listened = 2.5
            c.next_wave()
            until(lambda: len(c.wave_queue) == 2 and c.wave_started and not c.state["busy"])
            self.assertEqual(player.played, ["0", "1"])
            api.wave_batch.assert_any_call("user:onyourwave", "0", start=False)
            self.assertEqual([t.id for t, batch in c.wave_queue], ["2", "3"])
            self.assertTrue(all(batch == "second" for _, batch in c.wave_queue))
            until(lambda: api.feedback.call_count == 3)
            calls = [(a.args[1], a.args[2], a.args[3]) for a in api.feedback.call_args_list]
            self.assertEqual(calls, [("trackStarted", "0", "first"), ("skip", "0", "first"),
                                     ("trackStarted", "1", "first")])
            self.assertAlmostEqual(api.feedback.call_args_list[1].args[4], 2.5, delta=.05)
            self.assertEqual(api.report_play.call_count, 1)
            self.assertAlmostEqual(api.report_play.call_args.args[3], 2.5, delta=.05)
            c.show("history")
            until(lambda: not c.state["busy"])
            self.assertTrue(player.state["loaded"])
            self.assertEqual(c.state["view"], "history")
            # A stale refill from the previous station must not contaminate a new session.
            old = c.generation
            c._leave_wave()
            c._completed("wave", (old, WaveBatch("old", "old", tracks)), "")
            self.assertEqual(c.wave_queue, [])
        finally:
            c.close()

    def test_listening_time_does_not_count_seek_or_pause(self):
        import time
        api, player = Mock(), StubPlayer()
        c = PlaybackController(player, api)
        try:
            c.wave_started = True
            c.play_session = (Track("1", "Synthetic", "", 180, True), "play", "timestamp")
            player.state.update(loaded=True, paused=False, position=150)
            player.changed.emit()
            c.last_tick = time.monotonic() - 0.2
            c._tick()
            self.assertLess(c.listened, 0.5)
            player.state["paused"] = True
            player.changed.emit()
            before = c.listened
            c.last_tick -= 30
            c._tick()
            self.assertEqual(c.listened, before)
        finally:
            c.close()

    def test_eof_during_failed_browse_still_advances_wave(self):
        api, player = Mock(), StubPlayer()
        track = Track("2", "Synthetic", "", 180, True)
        api.stream.return_value = Stream(track, "https://example.test/private")
        c = PlaybackController(player, api)
        try:
            c.wave_station = "user:onyourwave"
            c.wave_queue = [(track, "next-batch")]
            c.active_wave = (c.wave_station, "1", "first-batch")
            c.wave_started = True
            c.pages["likes"]["status"] = "loading"
            player.ended.emit()
            c._completed("page", (("likes", 0, 0), None), "Сеть недоступна")
            until(lambda: player.played == ["2"] and c.wave_started)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
