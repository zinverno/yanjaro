"""Synthetic libpulse callbacks; no desktop, PCM acquisition or audio files."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime
runtime.configure()

from contextlib import contextmanager
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from core import Rejected
import core
import live
import personal_index
import pulse


@contextmanager
def server(events=(), stage="stream"):
    lib = MagicMock()
    lib.pa_mainloop_new.return_value = lib.pa_context_new.return_value = lib.pa_stream_new.return_value = 1
    lib.pa_context_connect.return_value = lib.pa_stream_set_monitor_stream.return_value = 0
    lib.pa_context_get_state.return_value = 4
    lib.pa_stream_get_state.return_value = 1
    lib.pa_stream_get_monitor_stream.return_value = 41
    pending = []

    def dispatch():
        while pending:
            event, index = pending.pop(0)
            callback = lib.pa_context_set_subscribe_callback.call_args.args[1]
            callback(1, event, index, None)

    def subscribe(context, mask, callback, data):
        callback(context, 1, data)
        if stage == "subscription":
            pending.extend(events)
            dispatch()
        return 1

    def connect(*args):
        if stage == "stream":
            pending.extend(events)
        elif stage == "ready":
            lib.pa_stream_get_state.return_value = 2
            pending.extend(events)
        return 0

    def iterate(*args):
        dispatch()
        lib.pa_stream_get_state.return_value = 2
        return 0

    lib.pa_context_subscribe.side_effect = subscribe
    lib.pa_stream_connect_record.side_effect = connect
    lib.pa_mainloop_iterate.side_effect = iterate
    # Seed owned RAM to prove wiping on constructor failure, even before return.
    pcm = np.full((15 * pulse.RATE, 2), .125, dtype=np.float32)
    with patch("pulse.C.CDLL", return_value=lib), patch("pulse.np.zeros", return_value=pcm), \
            patch("sys.stderr", new_callable=io.StringIO) as output:
        yield lib, pending, pcm, output


class PulseEventTests(unittest.TestCase):
    def assert_closed(self, lib, pcm, stream=True):
        if stream:
            lib.pa_stream_disconnect.assert_called_once_with(1)
            lib.pa_stream_unref.assert_called_once_with(1)
        else:
            lib.pa_stream_new.assert_not_called()
        lib.pa_context_disconnect.assert_called_once_with(1)
        lib.pa_context_unref.assert_called_once_with(1)
        lib.pa_mainloop_free.assert_called_once_with(1)
        self.assertTrue((pcm == 0).all())

    def test_unrelated_objects_in_both_phases_and_separate_index_namespaces(self):
        # A sink with the input's index is still unrelated, and vice versa.
        events = [(kind | facility, index) for kind in (0, 0x10, 0x20)
                  for facility, index in ((0, 8), (2, 42), (0, 41), (2, 7))]
        with server(events) as (lib, pending, pcm, output):
            cap = pulse.Capture("41", "7", "synthetic.monitor")
            try:
                self.assertEqual(cap.phase, "active_capture")
                pending.extend(events)
                cap.iterate()
                self.assertIsNone(cap.error)
                rows = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(len(rows), 2 * len(events))
                for phase, group in (("initialization", rows[:len(events)]),
                                     ("active_capture", rows[len(events):])):
                    self.assertTrue(all(row["phase"] == phase and row["decision"] == "IGNORE" and
                                        row["reason"] == "PULSE_UNRELATED_OBJECT" for row in group))
                lib.pa_context_subscribe.assert_called_once()
                self.assertEqual(lib.pa_context_subscribe.call_args.args[1], 5)
            finally:
                cap.close()
            self.assert_closed(lib, pcm)

    def test_selected_new_change_remove_reject_during_initialization_and_cleanup(self):
        for stage in ("subscription", "stream", "ready"):
            for facility, index, name in ((0, 7, "SINK"), (2, 41, "SINK_INPUT")):
                for kind, label in ((0, "NEW"), (0x10, "CHANGE"), (0x20, "REMOVE")):
                    with self.subTest(stage=stage, name=name, type=label), \
                            server([(facility | kind, index)], stage) as (lib, _, pcm, output):
                        reason = "PULSE_SELECTED_" + name + "_" + label
                        with self.assertRaisesRegex(Rejected, "^" + reason + "$"):
                            pulse.Capture(41, 7, "synthetic.monitor")
                        self.assertEqual(json.loads(output.getvalue()), dict(
                            event="PULSE_EVENT", facility=name, type=label, index=index,
                            phase="initialization", decision="REJECT", reason=reason))
                        self.assert_closed(lib, pcm, stream=stage != "subscription")

    def test_selected_events_reject_active_capture_even_without_metadata_change(self):
        for facility, index, name in ((0, 7, "SINK"), (2, 41, "SINK_INPUT")):
            for kind, label in ((0, "NEW"), (0x10, "CHANGE"), (0x20, "REMOVE")):
                with self.subTest(name=name, type=label), server() as (lib, pending, pcm, output):
                    cap = pulse.Capture(41, 7, "synthetic.monitor")
                    try:
                        pending.append((facility | kind, index))
                        reason = "PULSE_SELECTED_" + name + "_" + label
                        with self.assertRaisesRegex(Rejected, "^" + reason + "$"):
                            cap.iterate()
                        row = json.loads(output.getvalue())
                        self.assertEqual((row["phase"], row["decision"], row["reason"]),
                                         ("active_capture", "REJECT", reason))
                        # A later unrelated event never clears the rejection.
                        pending.append((0x10, 8))
                        with self.assertRaisesRegex(Rejected, "^" + reason + "$"):
                            cap.iterate()
                    finally:
                        cap.close()
                        cap.close()  # Cleanup is idempotent.
                    self.assert_closed(lib, pcm)

    def test_unknown_events_fail_closed(self):
        for event, index in ((0x30, 7), (0x50, 7), (0x11, 7), (0x10, 0xffffffff)):
            with self.subTest(event=event, index=index), server([(event, index)]) as (lib, _, pcm, output):
                with self.assertRaisesRegex(Rejected, "^PULSE_UNEXPECTED_EVENT$"):
                    pulse.Capture(41, 7, "synthetic.monitor")
                self.assertEqual(json.loads(output.getvalue())["decision"], "REJECT")
                self.assert_closed(lib, pcm)

    def test_diagnostic_is_allowlisted_and_never_includes_monitor_or_pcm(self):
        with server([(0x10, 8)]) as (_, _, pcm, output):
            cap = pulse.Capture(41, 7, "PRIVATE_SENTINEL_TOKEN_URL.monitor")
            cap.close()
            row = json.loads(output.getvalue())
            self.assertEqual(set(row), {"event", "facility", "type", "index", "phase", "decision", "reason"})
            self.assertIs(type(row["index"]), int)
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
            self.assertNotIn("0.125", output.getvalue())
            self.assertTrue((pcm == 0).all())

    def test_diagnostic_failure_does_not_escape_c_callback_or_accept_window(self):
        with server() as (lib, pending, pcm, _):
            cap = pulse.Capture(41, 7, "synthetic.monitor")
            try:
                pending.append((0x10, 8))
                with patch("pulse.sys.stderr.write", side_effect=OSError("PRIVATE_SENTINEL")):
                    with self.assertRaisesRegex(Rejected, "^PULSE_EVENT_CALLBACK_FAILED$"):
                        cap.iterate()
            finally:
                cap.close()
            self.assert_closed(lib, pcm)

    def test_invalid_sink_id_rejected_before_library_or_pcm(self):
        for sink in (-1, True, "invalid", 4294967295):
            with self.subTest(sink=sink), patch("pulse.C.CDLL") as library, patch("pulse.np.zeros") as pcm:
                with self.assertRaisesRegex(Rejected, "^INVALID_PULSE_OBJECT_ID$"):
                    pulse.Capture(41, sink, "synthetic.monitor")
                library.assert_not_called()
                pcm.assert_not_called()

    def test_cli_pulse_rejection_closes_resources_wipes_pcm_and_saves_no_vector(self):
        initial = dict(path=live.PATH + "/track_" + hashlib.sha256(b"123").hexdigest(),
                       title="Test", artists=["Test"], length=200000000,
                       status="Playing", position=30000000, volume=.6, rate=1.0)
        route = dict(index=41, sink=7, monitor="synthetic.monitor")
        for phase in ("initialization", "active_capture", "after_stop"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory(dir="/tmp") as tmp, \
                    server([(0x10, 7)] if phase == "initialization" else []) as (lib, pending, pcm, _):
                observer = MagicMock(pid=9137)
                observer.snapshot.return_value = initial
                def check(cap, started):
                    cap.frames = 10 * pulse.RATE
                    pending.append((0x10, 7))
                    if phase == "active_capture":
                        cap.iterate()
                directory = Path(tmp) / "private"
                with patch.object(sys, "argv", ["personal_index", "--live", "--track-id", "123",
                                                "--index-dir", str(directory)]), \
                        patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                        patch("live.Mpris", return_value=observer), patch("live.audio_route", return_value=route), \
                        patch("builtins.input", return_value="START 123"), patch("builtins.print"), \
                        patch("live.time.monotonic", return_value=0), patch("live.time.sleep"), \
                        patch("live.select.select", return_value=([sys.stdin], [], [])), \
                        patch("sys.stdin.readline", return_value="\n"), patch.object(pulse.Capture, "check", check), \
                        patch("personal_index.extract") as extract:
                    with self.assertRaisesRegex(Rejected, "^PULSE_SELECTED_SINK_CHANGE$"):
                        personal_index.main()
                    extract.assert_not_called()
                self.assert_closed(lib, pcm)
                observer.close.assert_called_once()
                self.assertEqual(core.Index(directory).records(), [])

    def test_final_event_check_does_not_extend_pcm_past_owner_stop(self):
        initial = dict(path=live.PATH + "/track_" + hashlib.sha256(b"123").hexdigest(),
                       title="Test", artists=["Test"], length=200000000,
                       status="Playing", position=30000000, volume=.6, rate=1.0)
        route = dict(index=41, sink=7, monitor="synthetic.monitor", stream_volume=[65536], sink_volume=[65536])
        with server() as (lib, pending, pcm, _):
            observer = MagicMock(pid=9137)
            observer.snapshot.return_value = initial
            def check(cap, started):
                cap.frames = 10 * pulse.RATE
                pending.append((0x10, 8))
                dispatch = lib.pa_mainloop_iterate.side_effect
                def final_iterate(*args):
                    dispatch(*args)
                    cap.append(np.full((pulse.RATE, 2), .25, dtype=np.float32))
                    return 0
                lib.pa_mainloop_iterate.side_effect = final_iterate
            with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                    patch("live.Mpris", return_value=observer), patch("live.audio_route", return_value=route), \
                    patch("builtins.input", return_value="START 123"), patch("builtins.print"), \
                    patch("live.time.monotonic", return_value=0), patch("live.time.sleep"), \
                    patch("live.select.select", return_value=([sys.stdin], [], [])), \
                    patch("sys.stdin.readline", return_value="\n"), patch.object(pulse.Capture, "check", check):
                accepted_pcm, *_ = live.capture_owner("123")
                try:
                    self.assertEqual(accepted_pcm.shape, (10 * pulse.RATE, 2))
                    self.assertTrue((accepted_pcm == .125).all())
                finally:
                    accepted_pcm.fill(0)
            self.assert_closed(lib, pcm)
            observer.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
