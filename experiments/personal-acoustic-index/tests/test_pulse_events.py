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


def records(output, event="PULSE_EVENT"):
    return [row for line in output.getvalue().splitlines() if (row := json.loads(line))["event"] == event]


@contextmanager
def server(events=(), stage="stream"):
    lib = MagicMock()
    lib.pa_mainloop_new.return_value = lib.pa_context_new.return_value = lib.pa_stream_new.return_value = 1
    lib.pa_context_connect.return_value = lib.pa_stream_set_monitor_stream.return_value = 0
    lib.pa_context_get_state.return_value = 4
    lib.pa_stream_get_state.return_value = 1
    lib.pa_stream_get_monitor_stream.return_value = 41
    lib.pa_stream_is_suspended.return_value = 0
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

    def local_stage(name, result):
        def call(*args):
            if name == "creation":
                lib.pa_stream_get_state.return_value = 1
            if stage == name:
                pending.extend(events)
                dispatch()
            return result
        return call

    def iterate(*args):
        dispatch()
        lib.pa_stream_get_state.return_value = 2
        return 0

    lib.pa_context_subscribe.side_effect = subscribe
    lib.pa_stream_new.side_effect = local_stage("creation", 1)
    lib.pa_stream_set_monitor_stream.side_effect = local_stage("binding", 0)
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
                rows = records(output)
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
        for stage in ("subscription", "creation", "binding", "stream", "ready"):
            for facility, index, name in ((0, 7, "SINK"), (2, 41, "SINK_INPUT")):
                for kind, label in ((0, "NEW"), (0x10, "CHANGE"), (0x20, "REMOVE")):
                    with self.subTest(stage=stage, name=name, type=label), \
                            server([(facility | kind, index)], stage) as (lib, _, pcm, output):
                        reason = "PULSE_SELECTED_" + name + "_" + label
                        with self.assertRaisesRegex(Rejected, "^" + reason + "$"):
                            pulse.Capture(41, 7, "synthetic.monitor")
                        row, = records(output)
                        self.assertEqual({k: v for k, v in row.items() if k not in ("stage", "observed_ms", "stage_ms")}, dict(
                            event="PULSE_EVENT", facility=name, type=label, index=index,
                            phase="initialization", decision="REJECT", reason=reason))
                        self.assertEqual(row["stage"], {"subscription": "subscription", "creation": "stream_creation",
                                         "binding": "monitor_binding", "stream": "record_connection", "ready": "ready"}[stage])
                        self.assertGreaterEqual(row["observed_ms"], row["stage_ms"])
                        self.assertGreaterEqual(row["stage_ms"], 0)
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
                        row, = records(output)
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
                self.assertEqual(records(output)[0]["decision"], "REJECT")
                self.assert_closed(lib, pcm)

    def test_diagnostic_is_allowlisted_and_never_includes_monitor_or_pcm(self):
        with server([(0x10, 8)]) as (_, _, pcm, output):
            cap = pulse.Capture(41, 7, "PRIVATE_SENTINEL_TOKEN_URL.monitor")
            cap.close()
            row, = records(output)
            self.assertEqual(set(row), {"event", "facility", "type", "index", "phase", "stage",
                                       "observed_ms", "stage_ms", "decision", "reason"})
            self.assertIs(type(row["index"]), int)
            self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
            self.assertTrue((pcm == 0).all())

    def test_stage_sequence_and_after_stop_remain_guarded(self):
        with server() as (lib, pending, pcm, output):
            cap = pulse.Capture(41, 7, "synthetic.monitor")
            try:
                self.assertEqual([r["stage"] for r in records(output, "PULSE_STAGE")],
                                 ["context_connection", "subscription", "stream_creation", "monitor_binding",
                                  "record_connection", "ready", "active_capture"])
                cap.phase = "after_stop"
                cap.set_stage("after_stop")
                pending.append((0x12, 41))
                with self.assertRaisesRegex(Rejected, "^PULSE_SELECTED_SINK_INPUT_CHANGE$"):
                    cap.iterate()
                row, = records(output)
                self.assertEqual((row["stage"], row["phase"], row["decision"]), ("after_stop", "after_stop", "REJECT"))
            finally:
                cap.close()
            self.assert_closed(lib, pcm)

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

    def test_real_read_callback_drops_post_stop_pcm_without_copy(self):
        with server() as (lib, _, pcm, _):
            cap = pulse.Capture(41, 7, "synthetic.monitor")
            cap.phase = "after_stop"
            cap.set_stage("after_stop")
            def peek(stream, pointer, count):
                pointer._obj.value = 1
                count._obj.value = 8
                return 0
            lib.pa_stream_peek.side_effect = peek
            lib.pa_stream_drop.return_value = 0
            with patch("pulse.np.ctypeslib.as_array", side_effect=AssertionError("PCM copied")):
                callback = lib.pa_stream_set_read_callback.call_args.args[1]
                callback(1, 8, None)
            self.assertIsNone(cap.error)
            self.assertEqual(cap.frames, 0)
            lib.pa_stream_drop.assert_called_once_with(1)
            cap.close()
            self.assert_closed(lib, pcm)


class PulseDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.monotonic = patch("pulse.time.monotonic", side_effect=lambda: self.now)
        self.sleep = patch("pulse.time.sleep", side_effect=self.advance)
        self.monotonic.start()
        self.sleep.start()
        self.addCleanup(self.monotonic.stop)
        self.addCleanup(self.sleep.stop)

    def advance(self, seconds):
        self.now += seconds

    def test_startup_changes_are_observed_only_and_later_changes_reject(self):
        for stage in ("subscription", "creation", "binding", "stream", "ready"):
            with self.subTest(stage=stage), server([(0x12, 41)], stage) as (lib, pending, _, output):
                verify = MagicMock()
                cap = pulse.Capture(41, 7, "synthetic.monitor", diagnostic=True, verify=verify)
                try:
                    self.assertIsNone(cap.pcm)
                    self.assertEqual(cap.phase, "diagnostic")
                    self.assertGreaterEqual(verify.call_count, 2)
                    row, = records(output)
                    self.assertEqual((row["decision"], row["phase"], row["reason"]),
                                     ("OBSERVE_ONLY", "initialization", "PULSE_SELECTED_SINK_INPUT_CHANGE"))
                    self.assertEqual(row["stage"], {"subscription": "subscription", "creation": "stream_creation",
                                     "binding": "monitor_binding", "stream": "record_connection", "ready": "ready"}[stage])
                    stages = [r["stage"] for r in records(output, "PULSE_STAGE")]
                    self.assertLess(stages.index("subscription_baseline"), stages.index("record_connection"))
                    self.assertLess(stages.index("route_revalidation"), stages.index("diagnostic_observation"))
                    self.assertNotIn("active_capture", stages)
                    pending.append((0x12, 41))
                    with self.assertRaisesRegex(Rejected, "^PULSE_SELECTED_SINK_INPUT_CHANGE$"):
                        cap.iterate()
                    self.assertEqual(records(output)[-1]["decision"], "REJECT")
                finally:
                    cap.close()
                lib.pa_stream_disconnect.assert_called_once()
                lib.pa_context_disconnect.assert_called_once()
                lib.pa_mainloop_free.assert_called_once()

    def test_diagnostic_never_relaxes_removal_new_or_unknown_events(self):
        for event in (2, 0x22, 0x32, 0x52):
            with self.subTest(event=event), server([(event, 41)]) as (lib, _, _, output):
                with self.assertRaises(Rejected):
                    pulse.Capture(41, 7, "synthetic.monitor", diagnostic=True, verify=MagicMock())
                self.assertEqual(records(output)[0]["decision"], "REJECT")
                lib.pa_stream_disconnect.assert_called_once()
                lib.pa_context_disconnect.assert_called_once()

    def test_counts_and_drops_pcm_without_dereferencing_or_allocating_capture_buffer(self):
        with server() as (lib, _, _, output), patch("pulse.np.zeros") as allocate:
            cap = pulse.Capture(41, 7, "synthetic.monitor", diagnostic=True, verify=MagicMock())
            try:
                def peek(stream, pointer, count):
                    pointer._obj.value = 1  # Deliberately invalid to dereference; diagnostics must never do so.
                    count._obj.value = 480 * 8
                    return 0
                lib.pa_stream_peek.side_effect = peek
                lib.pa_stream_drop.return_value = 0
                with patch("pulse.np.ctypeslib.as_array", side_effect=AssertionError("PCM copied")):
                    cap.read(1, 480 * 8, None)
                    cap.read(1, 480 * 8, None)
                self.assertIsNone(cap.error)
                self.assertEqual(cap.frames, 960)
                self.assertIsNone(cap.pcm)
                allocate.assert_not_called()
                self.assertEqual(lib.pa_stream_drop.call_count, 2)
                row, = records(output, "PULSE_PCM")
                self.assertEqual(row["disposition"], "DISCARDED_NO_COPY")
                with self.assertRaisesRegex(Rejected, "^DIAGNOSTIC_PCM_STORAGE_FORBIDDEN$"):
                    cap.append(np.ones((1, 2)))
            finally:
                cap.close()

    def test_guard_required_and_real_route_failure_closes_before_record_connection(self):
        with patch("pulse.C.CDLL") as library:
            with self.assertRaisesRegex(Rejected, "^DIAGNOSTIC_GUARD_REQUIRED$"):
                pulse.Capture(41, 7, "synthetic.monitor", diagnostic=True)
            library.assert_not_called()
        with server() as (lib, _, _, _):
            with self.assertRaisesRegex(Rejected, "^AUDIO_ROUTE_OR_GAIN_CHANGED$"):
                pulse.Capture(41, 7, "synthetic.monitor", diagnostic=True,
                              verify=MagicMock(side_effect=Rejected("AUDIO_ROUTE_OR_GAIN_CHANGED")))
            lib.pa_stream_new.assert_not_called()
            lib.pa_context_disconnect.assert_called_once()

    def test_diagnostic_pcm_holes_alignment_and_drop_errors_still_reject(self):
        for pointer_value, nbytes, drop, reason in ((None, 8, 0, "PCM_HOLE"),
                                                   (1, 7, 0, "PCM_FRAME_ALIGNMENT"),
                                                   (1, 8, -1, "PCM_DROP_FAILED")):
            with self.subTest(reason=reason), server() as (lib, _, _, _):
                cap = pulse.Capture(41, 7, "synthetic.monitor", diagnostic=True, verify=MagicMock())
                try:
                    def peek(stream, pointer, count):
                        pointer._obj.value = pointer_value
                        count._obj.value = nbytes
                        return 0
                    lib.pa_stream_peek.side_effect = peek
                    lib.pa_stream_drop.return_value = drop
                    callback = lib.pa_stream_set_read_callback.call_args.args[1]
                    callback(1, nbytes, None)
                    with self.assertRaisesRegex(Rejected, "^" + reason + "$"):
                        cap.iterate()
                    self.assertIsNone(cap.pcm)
                    lib.pa_stream_drop.assert_called_once()
                finally:
                    cap.close()

    def test_after_ready_revalidation_failure_and_deadline_close_capture(self):
        for failure in ("route", "deadline"):
            with self.subTest(failure=failure), server() as (lib, _, _, _):
                def verify():
                    if lib.pa_stream_connect_record.called:
                        if failure == "route":
                            raise Rejected("AUDIO_ROUTE_OR_GAIN_CHANGED")
                        self.advance(12)
                reason = "AUDIO_ROUTE_OR_GAIN_CHANGED" if failure == "route" else "PULSE_DIAGNOSTIC_TIMEOUT"
                with self.assertRaisesRegex(Rejected, "^" + reason + "$"):
                    pulse.Capture(41, 7, "synthetic.monitor", diagnostic=True, verify=verify)
                lib.pa_stream_disconnect.assert_called_once()
                lib.pa_mainloop_free.assert_called_once()

    def test_cli_one_bounded_diagnostic_without_index_dsp_or_pcm_storage(self):
        initial = dict(path=live.PATH + "/track_" + hashlib.sha256(b"123").hexdigest(),
                       title="Test", artists=["Test"], length=200000000,
                       status="Playing", position=30000000, volume=.6, rate=1.0)
        route = dict(index=41, sink=7, monitor="synthetic.monitor")
        for stop in ("automatic", "owner", "cancel", "after_stop_change"):
            with self.subTest(stop=stop), server([(0x12, 41)]) as (lib, pending, _, output):
                start = self.now
                observer = MagicMock(pid=9137)
                observer.snapshot.side_effect = lambda: dict(initial, position=30000000 + round((self.now-start) * 1e6))
                holder = []
                def check(cap, started):
                    holder.append(cap)
                    self.assertIsNone(cap.pcm)
                    if stop == "cancel":
                        raise KeyboardInterrupt()
                    cap.frames = (3 if stop == "automatic" else 1) * pulse.RATE
                    if stop == "after_stop_change":
                        pending.append((0x12, 41))
                with patch.object(sys, "argv", ["personal_index", "--diagnose-pulse", "--track-id", "123"]), \
                        patch("sys.stdin.isatty", return_value=True), patch("sys.stdout", new_callable=io.StringIO) as stdout, \
                        patch("live.Mpris", return_value=observer), patch("live.audio_route", return_value=route), \
                        patch("builtins.input", return_value="START 123"), \
                        patch("live.select.select", return_value=([] if stop == "automatic" else [sys.stdin], [], [])), \
                        patch("sys.stdin.readline", return_value="\n"), patch.object(pulse.Capture, "check", check), \
                        patch("personal_index.Index") as index, patch("personal_index.extract") as extract, \
                        patch("sys.stdout.isatty", return_value=True):
                    if stop == "cancel":
                        with self.assertRaises(KeyboardInterrupt):
                            personal_index.main()
                    elif stop == "after_stop_change":
                        with self.assertRaisesRegex(Rejected, "^PULSE_SELECTED_SINK_INPUT_CHANGE$"):
                            personal_index.main()
                        self.assertEqual(records(output)[-1]["stage"], "after_stop")
                    else:
                        personal_index.main()
                        result = json.loads(stdout.getvalue()[stdout.getvalue().index('{\n  "result"'):])["result"]
                        self.assertEqual(result["status"], "DIAGNOSTIC_ONLY")
                        self.assertFalse(result["accepted_capture"])
                        self.assertFalse(result["vector_saved"])
                        self.assertEqual(result["stop"], "AUTOMATIC_LIMIT" if stop == "automatic" else "OWNER_STOP")
                    index.assert_not_called()
                    extract.assert_not_called()
                self.assertEqual(len(holder), 1)
                lib.pa_stream_connect_record.assert_called_once()
                lib.pa_stream_disconnect.assert_called_once()
                observer.close.assert_called_once()

    def test_diagnostic_requires_tty_manual_start_and_valid_id(self):
        for args in (["--diagnose-pulse"], ["--diagnose-pulse", "--track-id", "bad"],
                     ["--diagnose-pulse", "--track-id", "123", "--replace"]):
            with self.subTest(args=args), patch.object(sys, "argv", ["personal_index", *args]), \
                    patch("personal_index.Index") as index, patch("live.Capture") as capture:
                with self.assertRaises(Rejected):
                    personal_index.main()
                index.assert_not_called()
                capture.assert_not_called()
        with patch("sys.stdin.isatty", return_value=False), patch("live.Mpris") as observer:
            with self.assertRaisesRegex(Rejected, "^OWNER_TERMINAL_REQUIRED$"):
                live.capture_owner("123", diagnostic=True)
            observer.assert_not_called()
        observer = MagicMock()
        observer.snapshot.return_value = dict(path=live.PATH + "/track_" + hashlib.sha256(b"123").hexdigest(),
                                             status="Playing", title="Test", artists=["Test"])
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("live.Mpris", return_value=observer), patch("live.audio_route", return_value={}), \
                patch("builtins.input", return_value="cancel"), patch("builtins.print"), patch("live.Capture") as capture:
            with self.assertRaisesRegex(Rejected, "^OWNER_CANCELLED$"):
                live.capture_owner("123", diagnostic=True)
            capture.assert_not_called()
        observer.close.assert_called_once()

    def test_diagnostic_revalidates_route_and_playback_after_monitor_ready(self):
        initial = dict(path=live.PATH + "/track_" + hashlib.sha256(b"123").hexdigest(),
                       title="Test", artists=["Test"], length=200000000,
                       status="Playing", position=30000000, volume=.6, rate=1.0)
        route = dict(index=41, sink=7, monitor="synthetic.monitor", client=13,
                     direct_pid="9137", client_pid="9137", stream_volume=[65536], sink_volume=[65536])
        changes = [("route", key, value, "AUDIO_ROUTE_OR_GAIN_CHANGED") for key, value in
                   (("sink", 8), ("client", 14), ("direct_pid", "9999"), ("client_pid", "9999"),
                    ("stream_volume", [32768]), ("sink_volume", [32768]))]
        changes += [("playback", "status", "Paused", "PLAYBACK_NOT_PLAYING"),
                    ("playback", "path", "another-track", "TRACK_OR_GAIN_CHANGED"),
                    ("playback", "volume", .3, "TRACK_OR_GAIN_CHANGED")]
        for target, key, value, reason in changes:
            with self.subTest(target=target, key=key), server([(0x12, 41)]) as (lib, _, _, output):
                start = self.now
                observer = MagicMock(pid=9137)
                def snapshot():
                    result = dict(initial, position=30000000 + round((self.now - start) * 1e6))
                    if target == "playback" and lib.pa_stream_connect_record.called:
                        result[key] = value
                    return result
                def audio_route(pid):
                    return dict(route, **{key: value}) if target == "route" and lib.pa_stream_connect_record.called else route
                observer.snapshot.side_effect = snapshot
                with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                        patch("live.Mpris", return_value=observer), patch("live.audio_route", side_effect=audio_route), \
                        patch("builtins.input", return_value="START 123"), patch("builtins.print"):
                    with self.assertRaisesRegex(Rejected, "^" + reason + "$"):
                        live.capture_owner("123", diagnostic=True)
                lib.pa_stream_disconnect.assert_called_once()
                lib.pa_context_disconnect.assert_called_once()
                lib.pa_mainloop_free.assert_called_once()
                observer.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
