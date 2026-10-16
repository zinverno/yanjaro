"""Synthetic Pulse metadata only: never connect to a desktop or open real PCM."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime
runtime.configure()

import copy
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import core
import live
import personal_index
import pulse


class AudioBindingTests(unittest.TestCase):
    def setUp(self):
        self.pid = 9137
        volume = {"front-left": {"value": 65536}, "front-right": {"value": 65536}}
        self.stream = dict(index=41, client=31, sink=7, mute=False, corked=False,
                           volume=volume, properties={"application.name": "mpv"})
        self.client = dict(index=31, properties={"application.process.id": str(self.pid),
                                               "application.name": "python3.14"})
        self.sink = dict(index=7, monitor_source="test_sink.monitor", mute=False, volume=volume)

    def route(self, streams=None, clients=None):
        return live.select_audio(self.pid, [self.stream] if streams is None else streams, [self.sink],
                                 [self.client] if clients is None else clients)

    def test_matching_direct_pid(self):
        self.stream["properties"]["application.process.id"] = str(self.pid)
        self.assertEqual(self.route()["index"], 41)
        # Direct PID remains usable when the known client's PID is not published.
        self.client["properties"].pop("application.process.id")
        self.assertEqual(self.route()["index"], 41)

    def test_missing_direct_pid_uses_linked_client(self):
        other_client = dict(index=32, properties={"application.process.id": "8192"})
        other = dict(self.stream, index=42, client=32)
        route = self.route([other, self.stream], [other_client, self.client])
        self.assertEqual(route["index"], 41)
        self.assertEqual(route["client"], 31)
        self.assertIsNone(route["direct_pid"])
        self.assertEqual(route["client_pid"], str(self.pid))

    def test_decimal_strings_match_integer_object_ids(self):
        self.stream.update(index="248", client="247", sink="57")
        self.sink["index"] = 57
        for client_index in (247, "247"):
            with self.subTest(client_index=client_index):
                self.client["index"] = client_index
                route = self.route()
                self.assertEqual((route["index"], route["client"], route["sink"]), (248, 247, 57))
                self.assertTrue(all(type(route[key]) is int for key in ("index", "client", "sink")))
        self.sink["index"] = "57"
        self.assertEqual(self.route(), route)

    def test_object_id_normalization_boundaries(self):
        for value, expected in ((0, 0), ("0", 0), ("000247", 247), ("0" * 5000, 0),
                                (4294967294, 4294967294), ("4294967294", 4294967294)):
            with self.subTest(value=str(value)[:20]):
                self.assertEqual(pulse.object_id(value), expected)
                self.assertIs(type(pulse.object_id(value)), int)
        for value in (True, False, -1, "-1", "", " ", "247 ", " 247", "+247", "1.0", "1e2",
                      "0xff", "٢٤٧", "２４７", "247\n", 247.0, None, [], {}, b"247",
                      4294967295, "4294967295", 4294967296, "4294967296", "9" * 5000):
            with self.subTest(value=str(value)[:20]):
                with self.assertRaisesRegex(core.Rejected, "^INVALID_PULSE_OBJECT_ID$"):
                    pulse.object_id(value)

    def test_invalid_object_ids_rejected_in_every_route_field(self):
        for item, field in ((self.stream, "index"), (self.stream, "client"), (self.stream, "sink"),
                            (self.client, "index"), (self.sink, "index")):
            original = item[field]
            for value in (False, -1, "", "invalid", "١", 1.5, 4294967295, "4294967296"):
                with self.subTest(field=field, value=value):
                    item[field] = value
                    with self.assertRaisesRegex(core.Rejected, "^INVALID_PULSE_OBJECT_ID$"):
                        self.route()
            item[field] = original

    def test_string_ids_keep_missing_conflict_and_ambiguity_rejections(self):
        self.stream.update(index="41", client="31", sink="7")
        self.client["index"] = "31"
        self.sink["index"] = "7"
        with self.assertRaisesRegex(core.Rejected, "^YANJARO_AUDIO_STREAM_NOT_FOUND$"):
            self.route(clients=[])
        with self.assertRaisesRegex(core.Rejected, "^YANJARO_AUDIO_STREAM_NOT_UNIQUE$"):
            self.route([self.stream, dict(self.stream, index="42")])
        self.stream["properties"]["application.process.id"] = "8192"
        with self.assertRaisesRegex(core.Rejected, "^AUDIO_PROCESS_ID_CONFLICT$"):
            self.route()
        self.stream["properties"]["application.process.id"] = str(self.pid)
        with self.assertRaisesRegex(core.Rejected, "^AUDIO_CLIENT_UNAVAILABLE$"):
            self.route(clients=[])
        # Numeric/string aliases must not collapse two clients into one trusted candidate.
        with self.assertRaisesRegex(core.Rejected, "^AUDIO_CLIENT_UNAVAILABLE$"):
            self.route(clients=[self.client, dict(self.client, index=31)])

    def test_libpulse_receives_numeric_target_and_checks_monitor_identity(self):
        self.stream["index"] = "41"
        route = self.route()
        for returned in (41, 42, 4294967295):
            with self.subTest(returned=returned):
                lib = MagicMock()
                lib.pa_context_connect.return_value = 0
                lib.pa_stream_set_monitor_stream.return_value = 0
                lib.pa_stream_connect_record.return_value = 0
                lib.pa_stream_get_monitor_stream.return_value = returned
                lib.pa_context_subscribe.side_effect = lambda ctx, mask, cb, data: (cb(ctx, 1, data), 1)[1]
                # Fake C function handles; no real library/server/PCM stream is opened.
                lib.pa_mainloop_new.return_value = lib.pa_context_new.return_value = lib.pa_stream_new.return_value = 1
                with patch("pulse.C.CDLL", return_value=lib), patch.object(pulse.Capture, "bind"), \
                        patch.object(pulse.Capture, "wait_ready"):
                    if returned == 41:
                        cap = pulse.Capture(route["index"], route["monitor"])
                        cap.close()
                    else:
                        with self.assertRaisesRegex(core.Rejected, "^MONITOR_TARGET_NOT_CONFIRMED$"):
                            pulse.Capture(route["index"], route["monitor"])
                lib.pa_stream_set_monitor_stream.assert_called_once_with(1, 41)
                self.assertIs(type(lib.pa_stream_set_monitor_stream.call_args.args[1]), int)
                lib.pa_stream_get_monitor_stream.assert_called_once_with(1)
                lib.pa_stream_disconnect.assert_called_once_with(1)
        for value in (-1, True, 4294967295):
            with self.subTest(value=value), patch("pulse.C.CDLL") as library:
                with self.assertRaisesRegex(core.Rejected, "^INVALID_PULSE_OBJECT_ID$"):
                    pulse.Capture(value, "test_sink.monitor")
                library.assert_not_called()

    def test_id_representation_changes_do_not_abort_capture(self):
        path = live.PATH + "/track_" + hashlib.sha256(b"123").hexdigest()
        initial = dict(path=path, title="Test", artists=["Test"], length=200000000,
                       status="Playing", position=30000000, volume=.6, rate=1.0)
        metadata = {"sink-inputs": [self.stream], "clients": [self.client], "sinks": [self.sink]}
        reads = 0
        def pactl(kind):
            nonlocal reads
            if kind == "sink-inputs":
                reads += 1
                convert = str if reads % 2 else int
                for item, keys in ((self.stream, ("index", "client", "sink")),
                                   (self.client, ("index",)), (self.sink, ("index",))):
                    for key in keys:
                        item[key] = convert(item[key])
            return metadata[kind]
        observer = MagicMock(pid=self.pid)
        observer.snapshot.side_effect = [initial, initial, dict(initial, position=40000000),
                                         dict(initial, position=40000000)]
        cap = MagicMock(frames=10 * live.RATE, pcm=np.ones((1, 2), dtype=np.float32))
        cap.close.side_effect = lambda: cap.pcm.fill(0)
        with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                patch("live.Mpris", return_value=observer), patch("live.pactl", side_effect=pactl), \
                patch("builtins.input", return_value="START 123"), patch("builtins.print"), \
                patch("live.time.monotonic", side_effect=[0, 10, 10]), \
                patch("live.select.select", return_value=([sys.stdin], [], [])), \
                patch("sys.stdin.readline", return_value="\n"), patch("live.Capture", return_value=cap) as capture:
            pcm, *_ = live.capture_owner("123")
            self.assertEqual(reads, 4)
            capture.assert_called_once_with(41, "test_sink.monitor")
            self.assertIs(type(capture.call_args.args[0]), int)
            cap.close.assert_called_once()
            self.assertTrue((cap.pcm == 0).all())
            pcm.fill(0)
        observer.close.assert_called_once()

    def test_probe_failure_does_not_retry_or_open_pcm(self):
        observer = MagicMock(pid=self.pid)
        with patch.object(sys, "argv", ["personal_index", "--probe"]), \
                patch("live.Mpris", return_value=observer), \
                patch("live.subprocess.run", return_value=MagicMock(returncode=1, stdout=b"")) as command, \
                patch("live.Capture") as capture, patch("personal_index.Index") as index:
            with self.assertRaisesRegex(core.Rejected, "^LOCAL_PULSE_METADATA_UNAVAILABLE$"):
                personal_index.main()
            command.assert_called_once()
            capture.assert_not_called()
            index.assert_not_called()
        observer.close.assert_called_once()

    def test_foreign_client_pid_never_selected_by_mpv_name(self):
        self.client["properties"]["application.process.id"] = "8192"
        with self.assertRaisesRegex(core.Rejected, "^YANJARO_AUDIO_STREAM_NOT_FOUND$"):
            self.route()

    def test_conflicting_direct_and_client_pids(self):
        for direct, client in ((str(self.pid), "8192"), ("8192", str(self.pid))):
            with self.subTest(direct=direct, client=client):
                self.stream["properties"]["application.process.id"] = direct
                self.client["properties"]["application.process.id"] = client
                with self.assertRaisesRegex(core.Rejected, "^AUDIO_PROCESS_ID_CONFLICT$"):
                    self.route()

    def test_multiple_candidates_are_distinct_from_no_match(self):
        with self.assertRaisesRegex(core.Rejected, "^YANJARO_AUDIO_STREAM_NOT_UNIQUE$"):
            self.route([self.stream, dict(self.stream, index=42)])

    def test_missing_unknown_or_ambiguous_client(self):
        for reference, clients in ((None, [self.client]), (999, [self.client]),
                                   (31, []), (31, [self.client, self.client])):
            for direct in (None, str(self.pid)):
                with self.subTest(reference=reference, direct=direct, clients=len(clients)):
                    stream = copy.deepcopy(self.stream)
                    stream.pop("client")
                    if reference is not None:
                        stream["client"] = reference
                    if direct is not None:
                        stream["properties"]["application.process.id"] = direct
                    reason = "AUDIO_CLIENT_UNAVAILABLE" if direct else "YANJARO_AUDIO_STREAM_NOT_FOUND"
                    with self.assertRaisesRegex(core.Rejected, "^" + reason + "$"):
                        self.route([stream], clients)

    def test_changed_binding_aborts_before_during_and_after_capture_without_vector(self):
        path = live.PATH + "/track_" + hashlib.sha256(b"123").hexdigest()
        initial = dict(path=path, title="Test", artists=["Test"], length=200000000,
                       status="Playing", position=30000000, volume=.6, rate=1.0)
        for phase in (2, 3, 4):  # Post-START preflight, periodic check, final check after STOP.
            for change in ("client", "client_pid", "direct_pid", "index", "sink"):
                with self.subTest(phase=phase, change=change), tempfile.TemporaryDirectory(dir="/tmp") as tmp:
                    metadata = {"sink-inputs": [copy.deepcopy(self.stream)],
                                "clients": [copy.deepcopy(self.client)], "sinks": [copy.deepcopy(self.sink)]}
                    reads = 0
                    def pactl(kind):
                        nonlocal reads
                        if kind == "sink-inputs":
                            reads += 1
                            if reads == phase:
                                stream, client = metadata["sink-inputs"][0], metadata["clients"][0]
                                if change == "client":
                                    stream["client"] = client["index"] = 32
                                elif change == "client_pid":
                                    client["properties"]["application.process.id"] = "8192"
                                elif change == "direct_pid":
                                    stream["properties"]["application.process.id"] = str(self.pid)
                                elif change == "index":
                                    stream["index"] = 42
                                else:
                                    stream["sink"] = metadata["sinks"][0]["index"] = 8
                                # Real changes still reject when all object IDs arrive as strings.
                                for item, keys in ((stream, ("index", "client", "sink")),
                                                   (client, ("index",)), (metadata["sinks"][0], ("index",))):
                                    for key in keys:
                                        item[key] = str(item[key])
                        return metadata[kind]
                    observer = MagicMock(pid=self.pid)
                    observer.snapshot.side_effect = [initial, initial, dict(initial, position=40000000),
                                                     dict(initial, position=40000000)]
                    cap = MagicMock(frames=10 * live.RATE, pcm=np.ones((1, 2), dtype=np.float32))
                    cap.close.side_effect = lambda: cap.pcm.fill(0)
                    directory = Path(tmp) / "private"
                    with patch.object(sys, "argv", ["personal_index", "--live", "--track-id", "123",
                                                    "--index-dir", str(directory)]), \
                            patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), \
                            patch("live.Mpris", return_value=observer), patch("live.pactl", side_effect=pactl), \
                            patch("builtins.input", return_value="START 123"), patch("builtins.print"), \
                            patch("live.time.monotonic", side_effect=[0, 10, 10]), \
                            patch("live.select.select", return_value=([sys.stdin], [], [])), \
                            patch("sys.stdin.readline", return_value="\n"), patch("live.Capture", return_value=cap) as capture, \
                            patch("personal_index.extract") as extract:
                        reason = "YANJARO_AUDIO_STREAM_NOT_FOUND" if change == "client_pid" else "AUDIO_ROUTE_OR_GAIN_CHANGED"
                        with self.assertRaisesRegex(core.Rejected, "^" + reason + "$"):
                            personal_index.main()
                        self.assertEqual(reads, phase)
                        extract.assert_not_called()
                        if phase == 2:
                            capture.assert_not_called()
                        else:
                            capture.assert_called_once_with(41, "test_sink.monitor")
                            cap.close.assert_called_once()
                            self.assertTrue((cap.pcm == 0).all())
                    observer.close.assert_called_once()
                    self.assertEqual(core.Index(directory).records(), [])

    def test_probe_is_read_only_and_never_opens_pcm_or_index(self):
        observer = MagicMock(pid=self.pid)
        observer.snapshot.return_value = {"status": "Playing"}
        self.stream.update(index="41", client="31", sink="7")
        self.client["index"] = "31"
        metadata = {"sink-inputs": [self.stream], "clients": [self.client], "sinks": [self.sink]}
        def run(command, **kwargs):
            self.assertEqual(command[:-1], ["pactl", "--server", live.SERVER, "-f", "json", "list"])
            return type("Result", (), {"returncode": 0, "stdout": json.dumps(metadata[command[-1]]).encode()})()
        with patch.object(sys, "argv", ["personal_index", "--probe"]), \
                patch("live.Mpris", return_value=observer), patch("live.subprocess.run", side_effect=run) as pactl, \
                patch("live.Capture") as capture, patch("personal_index.Index") as index, \
                patch("personal_index.extract") as extract, patch("sys.stdout", new_callable=io.StringIO) as output:
            personal_index.main()
            result = json.loads(output.getvalue())["result"]
            self.assertEqual(result["status"], "LOCAL_METADATA_READY")
            self.assertEqual(result["capture"], "NOT_RUN")
            self.assertEqual(result["pcm_streams_opened"], 0)
            self.assertEqual([call.args[0][-1] for call in pactl.call_args_list], ["sink-inputs", "sinks", "clients"])
            capture.assert_not_called()
            index.assert_not_called()
            extract.assert_not_called()
        observer.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
