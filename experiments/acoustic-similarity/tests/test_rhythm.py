"""Unit fixtures exercise contracts only; no fixture weights are saved or reported."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import mido
import numpy as np

from acoustic_similarity.data import digest, read_json
from acoustic_similarity.groove import Acquisition, LIMIT, RangeZip, SCHEMA
from acoustic_similarity.nsynth import prepare_note_triplets
from acoustic_similarity.rhythm import (COHORT_DIGEST, FEATURE_SCHEMA, TARGET_SCHEMA,
    annotation_distance, contrastive_arrays, make_triplets, midi_events, midi_target,
    rhythm_features, run, validate_dataset)


def rows_fixture():
    rows = []
    for split, drummer in (("train", "a"), ("validation", "b"), ("test", "c")):
        for record in range(3):
            for bar in (4, 8):
                target = np.zeros(144, dtype=int)
                target[[0, 4, 8, 12] if record < 2 else [1, 5, 9, 13]] = 1
                original = drummer + str(record)
                rows.append({"id": original + "#beat" + str(bar), "original_id": original,
                             "drummer": drummer, "split": split, "bpm": 120, "start_beat": bar,
                             "audio_sha256": digest(original), "midi_sha256": digest(original + "midi"),
                             "features": [record/4] * 128, "target": target.tolist(), "genre": "unused"})
    return rows


def dataset_fixture():
    rows = rows_fixture()
    return {"schema": SCHEMA, "feature_schema": FEATURE_SCHEMA, "target_schema": TARGET_SCHEMA,
            "kind": "real-performed-midi", "plan_sha256": "a"*64,
            "midi_archive_sha256": "651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e",
            "rows": rows, "triplets": make_triplets(rows)}


class RhythmTests(unittest.TestCase):
    def test_cohort_is_pinned_and_budgeted(self):
        plan = read_json(Path(__file__).parents[1] / "datasets/groove-cohort.json")
        self.assertEqual(digest(plan), COHORT_DIGEST)
        expected = sum(r["compressed_bytes"] + 1024 for r in plan["records"])
        self.assertLess(expected + plan["midi_bytes"] + plan["directory_bytes"] + plan["local_preflight_dataset_bytes"], LIMIT)
        groups = {}
        for r in plan["records"]:
            key = r["metadata"]["drummer"]
            self.assertIn(r["split"], ("train", "validation", "test"))
            self.assertEqual(groups.setdefault(key, r["split"]), r["split"])

    def test_midi_structure_uses_performed_events_and_checks_tempo(self):
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.extend([mido.MetaMessage("set_tempo", tempo=500000),
                      mido.MetaMessage("time_signature", numerator=4, denominator=4),
                      mido.Message("note_on", channel=9, note=36, velocity=100, time=480),
                      mido.Message("note_on", channel=9, note=38, velocity=100, time=480)])
        raw = io.BytesIO()
        midi.save(file=raw)
        events = midi_events(raw.getvalue(), 120)
        self.assertEqual(events, [(1., 0), (2., 1)])
        target = midi_target(events, 0)
        self.assertEqual([i for i, n in enumerate(target) if n], [4, 24])
        with self.assertRaisesRegex(ValueError, "tempo"):
            midi_events(raw.getvalue(), 100)

    def test_triplets_cannot_depend_on_audio_scores_or_genre(self):
        rows = rows_fixture()
        expected = make_triplets(rows)
        for r in rows:
            r["features"] = [100] * 128
            r["genre"] = "different genre"
        self.assertEqual(make_triplets(rows), expected)
        self.assertTrue(expected)
        lookup = {r["id"]: r for r in rows}
        for t in expected:
            records = [lookup[t[k]] for k in ("anchor", "positive", "negative")]
            self.assertEqual(len({r["original_id"] for r in records}), 3)
            self.assertEqual(len({r["bpm"] for r in records}), 1)

    def test_no_positive_from_a_derivative_of_same_recording(self):
        rows = rows_fixture()[:2]
        self.assertEqual(make_triplets(rows), [])

    def test_bpm_mismatch_removes_comparison(self):
        rows = rows_fixture()[:6]
        for r in rows[4:]:
            r["bpm"] = 121
        self.assertEqual(make_triplets(rows), [])

    def test_target_distance_known(self):
        self.assertEqual(annotation_distance([1, 0, 1], [1, 0, 1]), 0)
        self.assertEqual(annotation_distance([1, 0], [0, 1]), 1)

    def test_source_and_performer_leakage_rejected(self):
        for field in ("drummer", "original_id", "audio_sha256", "midi_sha256"):
            dataset = dataset_fixture()
            dataset["rows"][-1][field] = dataset["rows"][0][field]
            with self.assertRaises(ValueError):
                validate_dataset(dataset)

    def test_external_triplet_or_faked_target_source_rejected(self):
        dataset = dataset_fixture()
        validate_dataset(dataset)
        dataset["triplets"][0]["source"] = "dsp_similarity"
        with self.assertRaisesRegex(ValueError, "independent MIDI"):
            validate_dataset(dataset)

    def test_holdout_features_never_enter_training_arrays(self):
        dataset = dataset_fixture()
        before, _ = contrastive_arrays(dataset, "train")
        for r in dataset["rows"]:
            if r["split"] != "train":
                r["features"] = [-1] * 128
        after, _ = contrastive_arrays(dataset, "train")
        np.testing.assert_array_equal(before, after)

    def test_feature_gain_invariance_and_tempo_normalization(self):
        def clicks(bpm):
            sr = 16000
            y = np.zeros(round(4*60/bpm*sr))
            for beat in (0, .5, 1, 1.75, 2, 3):
                i = round(beat*60/bpm*sr)
                n = min(240, len(y)-i)
                y[i:i+n] = np.sin(np.arange(n)*.4)*np.exp(-np.arange(n)/40)
            return y
        y = clicks(100)
        a = rhythm_features(y, 16000, 100)
        b = rhythm_features(.2*y, 16000, 100)
        np.testing.assert_allclose(a, b, atol=1e-8)
        c = rhythm_features(clicks(140), 16000, 140)
        self.assertLess(np.mean((np.asarray(a)-c)**2), .015)
        with self.assertRaises(ValueError):
            rhythm_features(np.zeros(32000), 16000, 100)

    def test_real_training_cannot_run_locally(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "remote Actions"):
                run("does-not-exist", "/not-created")


class AcquisitionTests(unittest.TestCase):
    def test_ignored_range_rejected_before_body_read(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = "https://example.invalid/test"
        response.status = 200
        with tempfile.TemporaryDirectory() as tmp, patch("urllib.request.urlopen", return_value=response):
            client = Acquisition({"local_preflight_dataset_bytes": 0, "audio_etag": "pinned"}, Path(tmp)/"receipt.json")
            with self.assertRaisesRegex(ValueError, "Range unavailable"):
                client.fetch("https://example.invalid/test", 100, 0)
            response.read.assert_not_called()

    def test_budget_fails_before_request(self):
        with tempfile.TemporaryDirectory() as tmp, patch("urllib.request.urlopen") as call:
            client = Acquisition({"local_preflight_dataset_bytes": LIMIT}, Path(tmp)/"receipt.json")
            with self.assertRaisesRegex(ValueError, "budget"):
                client.fetch("https://example.invalid/test", 10)
            call.assert_not_called()

    def test_random_access_zip_fetches_only_member_ranges(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("recording.wav", b"unit fixture" * 100)
        raw = data.getvalue()
        directory_start = raw.index(b"PK\x01\x02")
        class FakeClient:
            plan = {"directory_offset": directory_start, "audio_bytes": len(raw), "audio_url": "unit-fixture"}
            requests = []
            def fetch(self, url, size, start):
                self.requests.append((start, size))
                return raw[start:start+size]
        client = FakeClient()
        archive = zipfile.ZipFile(RangeZip(client, raw[directory_start:]))
        self.assertEqual(archive.read("recording.wav"), b"unit fixture" * 100)
        self.assertTrue(client.requests)
        self.assertTrue(all(start < directory_start for start, _ in client.requests))


class NSynthTests(unittest.TestCase):
    def test_independent_instruments_and_matched_pitch_velocity(self):
        metadata = {}
        for instrument in range(24):
            for pitch, velocity in ((60, 100), (72, 100), (60, 50)):
                name = f"test_{instrument:03}-{pitch:03}-{velocity:03}"
                metadata[name] = {"note_str": name, "instrument_str": f"test_{instrument:03}",
                    "pitch": pitch, "velocity": velocity, "sample_rate": 16000,
                    "qualities": [int(instrument % 2 == 0), int(instrument % 2 == 1)] + [0]*8}
        plan = prepare_note_triplets(metadata)
        self.assertTrue(plan["triplets"])
        self.assertEqual(plan["training_status"], "NOT RUN")
        for t in plan["triplets"]:
            notes = [metadata[t[k]] for k in ("anchor", "positive", "negative")]
            self.assertEqual(len({n["pitch"] for n in notes}), 1)
            self.assertEqual({n["velocity"] for n in notes}, {100})
            self.assertEqual(len({n["instrument_str"] for n in notes}), 3)
            self.assertEqual(len({plan["instrument_splits"][n["instrument_str"]] for n in notes}), 1)


if __name__ == "__main__":
    unittest.main()
