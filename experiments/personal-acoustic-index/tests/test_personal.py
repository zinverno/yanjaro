"""No desktop capture, audio files, network calls or account credentials in tests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime
runtime.configure()

import copy
import ctypes as C
import hashlib
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

import core
from live import Mpris, check_snapshot, select_audio, signal_ok, capture_owner
from pulse import Capture, RATE


def signal(hz=220, sr=16000):
    t = np.arange(12 * sr) / sr
    envelope = .1 + .2 * np.exp(-(t % .4) / .025)
    return (envelope * np.sin(2 * np.pi * hz * t))[:, None].copy()


class PersonalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [core.extract(signal(hz), 16000, key, core.identity(), "file")
                    for key, hz in (("a", 220), ("b", 880), ("c", 1760))]

    def test_705_reuse_repeat_and_wipe(self):
        pcm = signal()
        row = core.extract(pcm, 16000, "a", core.identity(), "file")
        self.assertTrue((pcm == 0).all())
        self.assertEqual(row["profile"], self.rows[0]["profile"])
        self.assertEqual(sum(core.retrieval.SHAPES.values()), 705)
        self.assertEqual(len(row["profile"]["blocks"]["timbre"]), 85)
        self.assertEqual(len(row["profile"]["blocks"]["energy"]), 10)

    def test_real_id_never_inferred_from_mpris_hash(self):
        path = "/org/mpris/MediaPlayer2/track_" + hashlib.sha256(b"149359136").hexdigest()
        result = core.identity("149359136", path)
        self.assertTrue(result["mpris_hash_matches"])
        self.assertIsNone(result["observed_id"])
        self.assertIsNone(result["real_id"])
        self.assertFalse(result["master_match"])
        with self.assertRaisesRegex(core.Rejected, "MPRIS_ID_MISMATCH"):
            core.identity("9053074", path)
        with self.assertRaises(core.Rejected):
            core.track_id(path)

    def test_live_schema_preserves_observation_and_rejects_false_binding(self):
        path = "/org/mpris/MediaPlayer2/track_" + hashlib.sha256(b"123").hexdigest()
        capture = dict(method="libpulse-single-sink-input", sample_rate=48000, player_volume=.6,
                       sink_input_volume=[65536, 65536], sink_volume=[32768, 32768], position_start_us=30000000,
                       started_at="2026-10-16T00:00:00+00:00", stopped_at="2026-10-16T00:00:12+00:00")
        row = core.extract(signal(sr=48000), 48000, "yandex-123", core.identity("123", path), "live", capture=capture)
        self.assertEqual(row["observed_at"], capture["started_at"])
        self.assertEqual(row["profile"]["sample_rate"], 48000)
        row["identity"]["real_id"] = "456"
        with self.assertRaises(core.Rejected):
            core.validate_record(row)

    def test_silence_nan_dropouts_clipping_rejected_and_wiped(self):
        cases = [np.zeros((12 * 16000, 1)), signal(), signal(), signal()]
        cases[1][100] = np.nan
        cases[2][16000:24000] = 0
        cases[3][:16000] = 1.2
        for pcm in cases:
            with self.assertRaises(core.Rejected):
                core.extract(pcm, 16000, "x", core.identity(), "file")
            self.assertTrue((pcm == 0).all())

    def test_track_pause_gain_seek_and_event_loss(self):
        start = dict(path="hash", title="Title", artists=["Artist"], length=200000000,
                     status="Playing", position=30000000, volume=.6, rate=1.0)
        current = dict(start, position=31000000)
        check_snapshot(start, current, 1)
        for key, value in (("path", "different"), ("status", "Paused"), ("volume", .5), ("position", 70000000)):
            with self.assertRaises(core.Rejected):
                check_snapshot(start, dict(current, **{key: value}), 1)
        for member, body in (("Seeked", (1,)), ("PropertiesChanged", ("org.mpris.MediaPlayer2.Player", {"Metadata": ("a{sv}", {})}, [])),
                             ("PropertiesChanged", ("org.mpris.MediaPlayer2.Player", {}, ["PlaybackStatus"]))):
            with self.assertRaises(core.Rejected):
                signal_ok(member, body)
        from collections import deque
        monitor = Mpris.__new__(Mpris)
        monitor.messages = deque([None] * 65, maxlen=65)
        monitor.bus = SimpleNamespace(recv_messages=lambda **kw: (_ for _ in ()).throw(TimeoutError()))
        with self.assertRaisesRegex(core.Rejected, "MPRIS_EVENTS_LOST"):
            monitor.events()

    def test_process_binding_does_not_select_other_apps_or_mix(self):
        volume = {"front-left": {"value": 65536}, "front-right": {"value": 65536}}
        stream = dict(index=5, sink=2, client=3, properties={"application.process.id": "123"}, mute=False, corked=False, volume=volume)
        clients = [dict(index=3, properties={"application.process.id": "123"}),
                   dict(index=4, properties={"application.process.id": "456"})]
        sink = dict(index=2, monitor_source="test_sink.monitor", mute=False, volume=volume)
        other = dict(stream, index=6, client=4, properties={"application.process.id": "456"})
        self.assertEqual(select_audio(123, [other, stream], [sink], clients)["index"], 5)
        for streams in ([other], [stream, dict(stream, index=7)], [dict(stream, corked=True)]):
            with self.assertRaises(core.Rejected):
                select_audio(123, streams, [sink], clients)

    def test_pcm_holes_bad_alignment_loss_and_overflow_abort(self):
        cap = Capture.__new__(Capture)
        cap.diagnostic = False
        cap.stage = "active_capture"
        cap.pcm = np.zeros((15 * RATE, 2), dtype=np.float32)
        cap.frames = 0
        cap.first_data = cap.last_data = None
        for nbytes in (8, 7):
            cap.error = None
            def peek(stream, pointer, count):
                pointer._obj.value = None
                count._obj.value = nbytes
                return 0
            cap.lib = SimpleNamespace(pa_stream_peek=peek, pa_stream_drop=lambda stream: 0)
            cap.read(None, nbytes, None)
            self.assertEqual(cap.error, "PCM_HOLE")
        valid_pointer = (C.c_float * 2)(.1, .2)
        def unaligned(stream, pointer, count):
            pointer._obj.value = C.addressof(valid_pointer)
            count._obj.value = 7
            return 0
        cap.error = None
        cap.lib.pa_stream_peek = unaligned
        cap.read(None, 7, None)
        self.assertEqual(cap.error, "PCM_FRAME_ALIGNMENT")
        with self.assertRaisesRegex(core.Rejected, "OWNER_STOP_REQUIRED"):
            cap.append(np.zeros_like(cap.pcm))
        cap.error = "PULSE_OVERFLOW"
        cap.loop = None
        cap.lib = SimpleNamespace(pa_mainloop_iterate=lambda *args: 0)
        with self.assertRaisesRegex(core.Rejected, "PULSE_OVERFLOW"):
            cap.iterate()

    def test_gain_is_observed_not_normalized_to_master(self):
        reduced = core.extract(signal() * .5, 16000, "low", core.identity(), "file")
        self.assertAlmostEqual(reduced["quality"]["peak"], self.rows[0]["quality"]["peak"] * .5)
        difference = core.retrieval.compare(self.rows[0]["profile"], reduced["profile"])
        self.assertGreater(difference["components"]["energy"]["distance"], 0)

    def test_owner_cancellation_never_opens_pcm(self):
        path = "/org/mpris/MediaPlayer2/track_" + hashlib.sha256(b"123").hexdigest()
        observer = unittest.mock.MagicMock()
        observer.snapshot.return_value = {"path": path, "status": "Playing", "title": "Test", "artists": ["Test"]}
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("live.Mpris", return_value=observer), patch("live.pactl", return_value=[]), \
                patch("live.select_audio", return_value={}), patch("builtins.input", return_value="cancel"), \
                patch("builtins.print"), patch("live.Capture") as stream:
            with self.assertRaisesRegex(core.Rejected, "OWNER_CANCELLED"):
                capture_owner("123")
            stream.assert_not_called()
        observer.close.assert_called_once()

    def test_manual_live_start_is_required(self):
        with patch("sys.stdin.isatty", return_value=False), patch("live.Mpris") as m:
            with self.assertRaisesRegex(core.Rejected, "OWNER_TERMINAL_REQUIRED"):
                capture_owner("149359136")
            m.assert_not_called()

    def test_index_query_remeasurement_and_deletion(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temp:
            index = core.Index(Path(temp) / "private")
            self.assertEqual(index.put(self.rows[0]), "INSERTED")
            self.assertEqual(index.put(self.rows[0]), "UNCHANGED")
            with self.assertRaisesRegex(core.Rejected, "AT_LEAST_THREE"):
                index.search("a")
            for r in self.rows[1:]:
                index.put(r)
            result = index.search("a", 2)
            self.assertEqual({r["id"] for r in result["results"]}, {"b", "c"})
            self.assertEqual(set(result["results"][0]["components"]), {"rhythm", "tempo", "timbre", "energy"})
            changed = copy.deepcopy(self.rows[0])
            changed["profile"]["blocks"]["energy"][0] += .01
            with self.assertRaisesRegex(core.Rejected, "REMEASUREMENT_REQUIRES_REPLACE"):
                index.put(changed)
            self.assertEqual(index.put(changed, replace=True), "REPLACED")
            self.assertEqual(len(index.records()), 3)
            self.assertEqual(index.delete("b"), 1)
            self.assertEqual(index.delete(), 2)
            self.assertEqual(index.records(), [])
            self.assertNotIn(b'"profile"', index.path.read_bytes())

    def test_private_storage_and_no_audio_or_secrets(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temp:
            index = core.Index(Path(temp) / "private")
            index.put(self.rows[0])
            self.assertEqual(index.path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(index.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual([p.name for p in index.path.parent.iterdir()], ["index.sqlite3"])
            data = index.path.read_bytes()
            for forbidden in (b"RIFF", b"OggS", b"ID3", b"https://", b"Authorization", b"cookie", b"token"):
                self.assertNotIn(forbidden, data)
            bad = copy.deepcopy(self.rows[0]); bad["audio"] = [0, 1]
            with self.assertRaises(core.Rejected):
                index.put(bad)
            bad = copy.deepcopy(self.rows[0]); bad["quality"]["rms"] = "SECRET_SENTINEL"
            with self.assertRaises(core.Rejected):
                index.put(bad)
            public = Path(temp) / "public"; public.mkdir(mode=0o755)
            public.chmod(0o755)
            with self.assertRaises(core.Rejected):
                core.Index(public)
            link = Path(temp) / "linked"; link.symlink_to(index.path.parent)
            with self.assertRaises(core.Rejected):
                core.Index(link)

    def test_missing_tempo_is_not_a_perfect_match(self):
        row = copy.deepcopy(self.rows[1])
        row["profile"]["blocks"]["tempo"] = None
        row["profile"]["missing_reasons"]["tempo"] = "NO_QUALIFYING_TEMPO_PEAK"
        result = core.retrieval.compare(self.rows[0]["profile"], row["profile"])
        self.assertIsNone(result["components"]["tempo"]["distance"])
        self.assertLessEqual(result["coverage"], .75)
        self.assertEqual(result["quality"], "UNVALIDATED")

    def test_limits_are_enforced(self):
        import resource
        self.assertLessEqual(resource.getrlimit(resource.RLIMIT_AS)[0], 1024**3)
        self.assertLessEqual(len(os.sched_getaffinity(0)), 2)
        from threadpoolctl import threadpool_info
        self.assertTrue(all(p["num_threads"] <= 1 for p in threadpool_info()))


if __name__ == "__main__":
    unittest.main()
