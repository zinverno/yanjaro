import copy
from collections import Counter, defaultdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import numpy as np

from listening_study.analysis import analyze, validate_response
from listening_study.audio import extract, prepare, rights_ok
from listening_study.common import VERSION, digest, read_json, write_new
from listening_study.demo import build_demo, signal
from listening_study.design import compare, eligible, freeze, public_bundle, schedule, screen, tempo_distance, validate_study
from listening_study.metadata import import_mtg


def track(id="one", far=False, tags=False):
    return {"id": id, "artist_id": id, "source_sha256": id, "clip_sha256": id,
            "seconds": 10, "genre": ["rock" if tags else "jazz"], "instrument": ["guitar" if tags else "piano"],
            "features": {"bpm": 170 if far else 120, "onsets_per_second": 8 if far else 2,
                         "onset_regularity": .3 if far else .95, "onset_strength": .2 if far else .8,
                         "rms_db": -23, "dynamic_range_db": 5 if far else 25}}


def response(study, slot=0, prompt="next", first=True):
    data = {k: study[k] for k in ("schema", "study_id", "demo", "phase")}
    data.update(study_sha256=study["sha256"], slot=slot, prompt_id=prompt, participant_id=str(uuid.uuid4()),
                status="complete", answers=[])
    for t in schedule(study, slot, prompt):
        data["answers"].append({"trial_id": t["id"], "choice": "left" if first == t["first_left"] else "right",
                                "heard": dict.fromkeys(("source", "left", "right"), True)})
    return data


class SelectionTests(unittest.TestCase):
    def test_four_conditions(self):
        source = track()
        for far, tags, condition in ((False, True, "A"), (True, False, "B"), (False, False, "C"), (True, True, "D")):
            with self.subTest(condition=condition):
                self.assertEqual(compare(source, track("two", far, tags))["condition"], condition)

    def test_missing_is_unknown_even_when_both_missing(self):
        for key in ("genre", "instrument"):
            for both in (False, True):
                a, b = track(), track("two")
                a[key] = []
                if both:
                    b[key] = []
                self.assertIsNone(compare(a, b)["condition"])

    def test_tempo_aliases_and_not_fourfold(self):
        self.assertEqual(tempo_distance(60, 120), 0)
        self.assertEqual(tempo_distance(120, 240), 0)
        self.assertGreater(tempo_distance(60, 240), .9)
        self.assertEqual(tempo_distance(70, 100), tempo_distance(100, 70))

    def test_ambiguous_or_nonfinite_tempo_excluded(self):
        for value in (None, 0, float("nan"), float("inf"), True):
            a = track(); a["features"]["bpm"] = value
            self.assertIsNone(compare(a, track("two"))["condition"])

    def test_gray_zone_not_forced(self):
        a, b = track(), track("two")
        b["features"]["onset_strength"] = .6
        self.assertIsNone(compare(a, b)["condition"])

    def test_half_time_does_not_erase_onset_difference(self):
        a, b = track(), track("two")
        b["features"]["bpm"] = 60
        self.assertEqual(compare(a, b)["condition"], "C")
        b["features"]["onsets_per_second"] = 8
        self.assertIsNone(compare(a, b)["condition"])

    def test_duplicate_artist_audio_and_duration_excluded(self):
        a, b = track(), track("two")
        self.assertTrue(eligible(a, b))
        for key in ("id", "artist_id", "source_sha256", "clip_sha256"):
            changed = copy.deepcopy(b); changed[key] = a[key]
            self.assertFalse(eligible(a, changed))
        b["seconds"] = 12
        self.assertFalse(eligible(a, b))

    def test_spectral_features_are_diagnostic_not_rhythm(self):
        a, b = track(), track("two")
        b["features"].update(centroid_hz=7000, spectral_flatness=1)
        self.assertEqual(compare(a, b)["condition"], "C")


class AudioTests(unittest.TestCase):
    def test_pulses_and_determinism(self):
        y = signal(220)
        a = extract(y, 16000)
        self.assertEqual(a, extract(y, 16000))
        self.assertAlmostEqual(a["bpm"], 120, delta=3)
        self.assertEqual(a["bpm_alternatives"], [60, 120, 240])
        self.assertTrue(0 <= a["dynamic_range_db"] <= 80)
        self.assertAlmostEqual(a["centroid_hz"], 220, delta=10)

    def test_silence_nonfinite_short_rejected(self):
        for y in (np.zeros(160000), np.full(160000, np.nan), np.ones(400)):
            with self.assertRaises(ValueError):
                extract(y, 16000)

    def test_permissions_are_not_inferred_from_license(self):
        with self.assertRaises(ValueError):
            rights_ok({"license": "CC-BY-4.0"})

    def test_preflight_before_reading_audio(self):
        rows = [{**track(str(i)), "path": "/not/a/file", "start": 0, "seconds": 8, "rights": {}} for i in range(3)]
        with tempfile.TemporaryDirectory() as directory, patch("listening_study.audio.sf.SoundFile") as decode:
            with self.assertRaises(ValueError):
                prepare({"schema": VERSION, "demo": False, "tracks": rows}, Path(directory) / "new")
            decode.assert_not_called()

    def test_sample_bound(self):
        with self.assertRaises(ValueError):
            prepare({"schema": VERSION, "demo": False, "tracks": [track(str(i)) for i in range(61)]}, "/tmp/unused")


class MetadataTests(unittest.TestCase):
    def test_mtg_positive_annotations_and_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.tsv"
            path.write_text("TRACK_ID\tARTIST_ID\tALBUM_ID\tPATH\tDURATION\tTAGS\n"
                            "track_01\tartist_01\talbum_01\t../unsafe.mp3\t40\tgenre---rock,pop\tinstrument---guitar\n"
                            "track_02\tartist_02\talbum_02\t02.mp3\t50\tgenre---jazz\n")
            data = import_mtg(path, ["track_01", "track_02"], "a" * 40)
            self.assertEqual(data["tracks"][0]["genre"], ["pop", "rock"])
            self.assertEqual(data["tracks"][1]["instrument"], [])
            self.assertNotIn("path", data["tracks"][0])
            self.assertEqual(data["metadata_license"], "CC-BY-NC-SA-4.0")
            with self.assertRaises(ValueError):
                import_mtg(path, ["track_99"], "a" * 40)

    def test_revision_and_size_required(self):
        for ids, revision in ((["track_1"], "main"), (["track_1"] * 61, "a" * 40)):
            with self.assertRaises(ValueError):
                import_mtg("/missing", ids, revision)


class StudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name) / "demo"
        # Demo/extraction must never open a network socket.
        with patch("socket.socket", side_effect=AssertionError("unexpected network")):
            cls.study = build_demo(cls.root)
        cls.catalog = read_json(cls.root / "prepared/catalog.json")
        cls.review = read_json(cls.root / "demo-review.json")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_demo_is_explicit_and_audio_hashes_validate(self):
        self.assertTrue(self.study["demo"])
        self.assertEqual(self.study["phase"], "demo")
        validate_study(self.study, audio=True)
        self.assertEqual(len(list((self.root / "responses").glob("*.json"))), 32)

    def test_unreviewed_pairs_cannot_freeze(self):
        review = screen(self.catalog); review["trials"] = self.study["trials"]
        with self.assertRaisesRegex(ValueError, "Manual"):
            freeze(self.catalog, review, study_id="test", seed=1, phase="demo")

    def test_demo_cannot_be_silently_relabelled_pilot(self):
        with self.assertRaises(ValueError):
            freeze(self.catalog, self.review, study_id="test", seed=1, phase="pilot")

    def test_changed_catalog_and_policy_reject_old_review(self):
        for key, value in (("catalog_sha256", "bad"), ("policy", {})):
            review = copy.deepcopy(self.review); review[key] = value
            with self.assertRaises(ValueError):
                freeze(self.catalog, review, study_id="test", seed=1, phase="demo")

    def test_edited_manifest_detected(self):
        study = copy.deepcopy(self.study); study["seed"] = 1
        with self.assertRaises(ValueError):
            validate_study(study)

    def test_write_never_replaces(self):
        path = self.root / "no-overwrite.json"
        write_new(path, {"frozen": True})
        with self.assertRaises(FileExistsError):
            write_new(path, {"frozen": False})
        self.assertEqual(read_json(path), {"frozen": True})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_schedule_reproducible_and_block_balanced(self):
        for prompt in ("next", "similarity"):
            for n in (7, 8):
                study = copy.deepcopy(self.study); study["trials"] = study["trials"][:n]
                study["sha256"] = digest({k: v for k, v in study.items() if k != "sha256"})
                positions, orientations = defaultdict(Counter), defaultdict(Counter)
                for slot in range(2 * n):
                    tasks = schedule(study, slot, prompt)
                    self.assertEqual(tasks, schedule(study, slot, prompt))
                    self.assertEqual(len({t["id"] for t in tasks}), n)
                    self.assertLessEqual(abs(sum(t["first_left"] for t in tasks) * 2 - n), 1)
                    for position, task in enumerate(tasks):
                        positions[task["id"]][position] += 1
                        orientations[task["id"]][task["first_left"]] += 1
                for counts in positions.values():
                    self.assertEqual(list(sorted(counts.values())), [2] * n)
                for counts in orientations.values():
                    self.assertEqual(counts, {True: n, False: n})

    def test_invalid_slots(self):
        for slot in (-1, True, 10000, "1"):
            with self.assertRaises(ValueError):
                schedule(self.study, slot, "next")

    def test_public_allowlist_has_no_conditions_metadata_or_paths(self):
        data = public_bundle(self.study, 0, "next")
        for task in data["trials"]:
            self.assertEqual(set(task), {"id", "source", "left", "right"})
            for role in ("source", "left", "right"):
                self.assertRegex(task[role], r"^/audio/[0-9a-f]{32}$")
        text = json.dumps(data)
        for private in ("demo_group", "synthetic_d", "first_left", "rights", "clip_sha256", str(self.root)):
            self.assertNotIn(private, text)

    def test_response_rejects_personal_fields(self):
        for key in ("name", "email", "token", "user_agent", "ip", "timestamp"):
            data = response(self.study); data[key] = "do-not-retain"
            with self.assertRaises(ValueError):
                validate_response(data, self.study)
        data = response(self.study); data["answers"][0]["comment"] = "free text"
        with self.assertRaises(ValueError):
            validate_response(data, self.study)

    def test_response_rejects_bad_provenance_order_and_listening(self):
        mutations = [lambda r: r.update(study_sha256="wrong"), lambda r: r.update(demo=1),
                     lambda r: r.update(status="withdrawn"), lambda r: r.update(participant_id="name"),
                     lambda r: r["answers"].reverse(), lambda r: r["answers"].pop(),
                     lambda r: r["answers"][0].update(choice="A"),
                     lambda r: r["answers"][0]["heard"].update(source=False)]
        for mutate in mutations:
            data = response(self.study); mutate(data)
            with self.assertRaises(ValueError):
                validate_response(data, self.study)

    def test_metrics_and_participant_clusters(self):
        data = [response(self.study, 0, first=True), response(self.study, 1, first=False)]
        report = analyze(self.study, data, draws=300)
        result = report["results_by_prompt"]["next"]
        self.assertEqual(result["rhythm_share_among_decisive"], .5)
        self.assertEqual(result["decisive_choices"], 12)
        self.assertEqual(result["primary_sources"], 6)
        self.assertEqual(result["participant_cluster_bootstrap"]["ci95"], [0, 1])
        self.assertEqual(set(result["leave_one_source_out"].values()), {.5})
        self.assertEqual(result["control_outcomes"], {"both_near": 2, "both_far": 2})
        self.assertEqual(report, analyze(self.study, data, draws=300))

    def test_no_decisive_votes_is_unknown_not_zero(self):
        data = [response(self.study, 0), response(self.study, 1)]
        for row in data:
            for i, answer in enumerate(row["answers"]):
                answer["choice"] = "skip" if i % 2 else "neither"
                answer["heard"] = dict.fromkeys(("source", "left", "right"), answer["choice"] != "skip")
        result = analyze(self.study, data, draws=200)["results_by_prompt"]["next"]
        self.assertIsNone(result["rhythm_share_among_decisive"])
        self.assertIsNone(result["participant_cluster_bootstrap"]["ci95"])
        self.assertEqual(result["primary_trials"], 12)

    def test_wordings_never_pooled(self):
        data = [response(self.study, 0, "next", True), response(self.study, 0, "similarity", False)]
        result = analyze(self.study, data, draws=200)["results_by_prompt"]
        self.assertEqual(result["next"]["rhythm_share_among_decisive"], 1)
        self.assertEqual(result["similarity"]["rhythm_share_among_decisive"], 0)
        self.assertIsNone(result["next"]["participant_cluster_bootstrap"]["ci95"])

    def test_source_sensitivity_detects_influential_song(self):
        data = [response(self.study, slot, first=False) for slot in range(4)]
        for row in data:
            for answer, task in zip(row["answers"], schedule(self.study, row["slot"], "next")):
                if task["source"] == "d000":
                    answer["choice"] = "left" if task["first_left"] else "right"
        result = analyze(self.study, data, draws=200)["results_by_prompt"]["next"]
        self.assertEqual(result["rhythm_share_among_decisive"], 1 / 6)
        self.assertEqual(result["leave_one_source_out"]["d000"], 0)
        low, high = result["crossed_participant_source_bootstrap"]["ci95"]
        self.assertEqual(low, 0)
        self.assertGreater(high, 1 / 6)

    def test_duplicate_participant_or_slot_rejected(self):
        data = response(self.study)
        for second in (copy.deepcopy(data), response(self.study)):
            with self.assertRaises(ValueError):
                analyze(self.study, [data, second], draws=200)


if __name__ == "__main__":
    unittest.main()
