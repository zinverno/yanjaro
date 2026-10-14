import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from acoustic_similarity.cli import main, search
from acoustic_similarity.data import (ASPECTS, CASES, SCHEMA, digest, file_hash, read_json,
                                      artist_clusters, validate_labels, validate_manifest, write_new)
from acoustic_similarity.evaluate import evaluate, summary
from acoustic_similarity.features import (DIMENSIONS, FEATURE_SCHEMA, build_index, extract,
                                          tempo_distance, validate_index)
from acoustic_similarity.model import (ENCODER_ID, POOLING, distances, fit_head, train,
                                       validate_embeddings, validate_model, vectors)
from acoustic_similarity.remote import check_snapshot, extract_embeddings


def fixture():
    """Manufactured arrays only; these are never presented as encoder output."""
    rng = np.random.default_rng(17)
    manifest = {"schema": SCHEMA, "kind": "synthetic-test-only", "dataset_id": "test-1", "tracks": []}
    rows, embeds, triplets = [], [], []
    for split in ("train", "validation", "test"):
        ids = [split + str(i) for i in range(3)]
        for i, tid in enumerate(ids):
            sha = digest(tid)
            manifest["tracks"].append({"id": tid, "sha256": sha, "path": "unused.wav", "split": split,
                "artist_ids": [tid], "recording_group": tid, "start": 0, "seconds": 10,
                "rights": {"reviewed": True, "acquisition": True, "analysis": True, "training": True,
                           "remote": True, "license": "CC0-1.0", "source_url": "generated:test",
                           "evidence_path": "unused.txt", "evidence_sha256": digest("test"),
                           "attribution": "synthetic test generator", "scope": "test only", "verified_on": "2026-10-11"}})
            rows.append({"id": tid, "sha256": sha, "bpm": 120., "vectors":
                         {k: rng.uniform(-1, 1, d).tolist() for k, d in DIMENSIONS.items()}})
            embeds.append({"id": tid, "sha256": sha, "embedding": rng.normal(size=1536).tolist()})
        for k in ASPECTS:
            triplets.append({"anchor": ids[0], "positive": ids[1], "negative": ids[2], "aspect": k,
                             "source": "synthetic-test-only", "reviewer_ids": ["fixture-a", "fixture-b"],
                             "agreement": "agreed", "evidence": "manufactured-test", "cases": list(CASES)})
    index = {"schema": SCHEMA, "feature_schema": FEATURE_SCHEMA, "dataset_sha256": digest(manifest),
             "kind": manifest["kind"], "code_sha256": digest("test-code"), "tracks": rows}
    cache = {"schema": SCHEMA, "dataset_sha256": digest(manifest), "kind": manifest["kind"],
             "encoder": {"id": ENCODER_ID, "revision": "a" * 40, "snapshot_sha256": digest("fake"),
                         "pooling": POOLING, "frozen": True, "dimension": 1536, "weights_license": "CC-BY-NC-4.0"},
             "tracks": embeds}
    labels = {"schema": SCHEMA, "kind": manifest["kind"], "dataset_sha256": digest(manifest),
              "purpose": "acoustic_similarity", "triplets": triplets}
    return manifest, index, labels, cache


class Contracts(unittest.TestCase):
    def setUp(self):
        self.m, self.i, self.l, self.c = fixture()

    def test_fixture_contracts(self):
        self.assertEqual(len(validate_manifest(self.m)), 9)
        self.assertEqual(len(validate_index(self.i, self.m)), 9)
        self.assertEqual(len(validate_labels(self.l, self.m)), 9)
        self.assertEqual(len(validate_embeddings(self.c, self.i)), 9)

    def test_artist_and_collaboration_leakage(self):
        for field, value in (("artist_ids", ["test0", "train0"]), ("recording_group", "train0")):
            m = deepcopy(self.m)
            m["tracks"][-1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "leakage"):
                validate_manifest(m)

    def test_duplicate_audio(self):
        self.m["tracks"][1]["sha256"] = self.m["tracks"][0]["sha256"]
        with self.assertRaisesRegex(ValueError, "duplicate audio"):
            validate_manifest(self.m)

    def test_collaborators_form_one_independent_cluster(self):
        self.m["tracks"][0]["artist_ids"] = ["a", "b"]
        self.m["tracks"][1]["artist_ids"] = ["b", "c"]
        self.m["tracks"][2]["artist_ids"] = ["c"]
        groups = artist_clusters(validate_manifest(self.m))
        self.assertEqual(len({groups["train" + str(i)] for i in range(3)}), 1)

    def test_rights_fail_before_decode(self):
        self.m["tracks"][-1]["rights"]["analysis"] = False
        with patch("acoustic_similarity.features.extract") as decode:
            with self.assertRaisesRegex(ValueError, "rights"):
                build_index(self.m)
            decode.assert_not_called()

    def test_no_preference_or_genre_labels(self):
        for source in ("yambda_like", "dislike", "next_song", "genre", "dsp_threshold"):
            l = deepcopy(self.l)
            l["triplets"][0]["source"] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_labels(l, self.m)

    def test_duplicate_contradictory_labels(self):
        t = deepcopy(self.l["triplets"][0])
        t["positive"], t["negative"] = t["negative"], t["positive"]
        self.l["triplets"].append(t)
        with self.assertRaisesRegex(ValueError, "contradictory"):
            validate_labels(self.l, self.m)

    def test_labels_cannot_cross_split_or_dataset(self):
        self.l["triplets"][0]["negative"] = "test0"
        with self.assertRaisesRegex(ValueError, "crosses split"):
            validate_labels(self.l, self.m)
        self.l["dataset_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "another dataset"):
            validate_labels(self.l, self.m)

    def test_index_corruption(self):
        for value in ([float("nan")] * 72, [0.] * 71, [4.] * 72):
            i = deepcopy(self.i)
            i["tracks"][0]["vectors"]["rhythm"] = value
            with self.assertRaises(ValueError):
                validate_index(i, self.m)

    def test_embeddings_are_hash_bound_and_frozen(self):
        for key, value in (("sha256", "f" * 64), ("embedding", [0.] * 1536), ("embedding", [1.] * 768),
                           ("embedding", [1e308] * 1536)):
            c = deepcopy(self.c)
            c["tracks"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_embeddings(c, self.i)
        self.c["encoder"]["frozen"] = False
        with self.assertRaises(ValueError):
            validate_embeddings(self.c, self.i)

    def test_tempo_is_explicit_symmetric_and_unknown_not_equal(self):
        self.assertEqual(tempo_distance(120, 120), 0)
        self.assertAlmostEqual(tempo_distance(60, 120), .15)
        self.assertEqual(tempo_distance(97, 130), tempo_distance(130, 97))
        self.assertGreater(tempo_distance(None, None), 0)

    def test_genre_metadata_never_changes_distances(self):
        bank, rows = vectors(self.i, self.m, self.c)
        before = distances("train0", "train1", rows, bank)
        self.m["tracks"][0]["genre"] = "jazz"
        self.m["tracks"][1]["genre"] = "metal"
        self.i["dataset_sha256"] = digest(self.m)
        self.c["dataset_sha256"] = digest(self.m)
        bank, rows = vectors(self.i, self.m, self.c)
        self.assertEqual(before, distances("train0", "train1", rows, bank))

    def test_independent_aspect_inputs(self):
        bank, rows = vectors(self.i, self.m, self.c)
        before = distances("train0", "train1", rows, bank)
        bank["train1"]["timbre"] *= .1
        after = distances("train0", "train1", rows, bank)
        self.assertEqual(before["rhythm"], after["rhythm"])
        self.assertEqual(before["energy"], after["energy"])
        self.assertNotEqual(before["timbre"], after["timbre"])

    def test_optimizer_learns_known_ordering(self):
        X = np.tile([1., -.2], (8, 1))
        w, loss = fit_head(X, np.zeros(8))
        self.assertGreater(float(X[0].mean()), 0)
        self.assertLess(float(X[0] @ w), 0)
        self.assertTrue(np.isfinite(loss))

    def test_train_reproducible_and_encoder_untouched(self):
        original = deepcopy(self.c)
        a = train(self.m, self.i, self.l, self.c, allow_synthetic=True)
        b = train(self.m, self.i, self.l, self.c, allow_synthetic=True)
        self.assertEqual(a, b)
        self.assertEqual(self.c, original)
        self.assertEqual(a["status"], "SYNTHETIC TEST ONLY")

    def test_test_features_never_change_fit(self):
        a = train(self.m, self.i, self.l, self.c, allow_synthetic=True)
        for t in self.i["tracks"][-3:]:
            t["vectors"] = {k: [2.] * d for k, d in DIMENSIONS.items()}
        for t in self.c["tracks"][-3:]:
            t["embedding"] = [3.] * 1536
        b = train(self.m, self.i, self.l, self.c, allow_synthetic=True)
        self.assertEqual(a["weights"], b["weights"])
        self.assertEqual(a["train_loss"], b["train_loss"])

    def test_real_training_insufficient_data_is_rejected(self):
        self.m["kind"] = self.i["kind"] = self.l["kind"] = self.c["kind"] = "real"
        for t in self.l["triplets"]:
            t["source"] = "human_acoustic_comparison"
        for obj in (self.i, self.l, self.c):
            obj["dataset_sha256"] = digest(self.m)
        with self.assertRaisesRegex(ValueError, "NOT RUN"):
            train(self.m, self.i, self.l, self.c)

    def test_demo_model_rejected_by_default(self):
        with self.assertRaisesRegex(ValueError, "test-only"):
            train(self.m, self.i, self.l, self.c)
        model = train(self.m, self.i, self.l, self.c, allow_synthetic=True)
        bank, _ = vectors(self.i, self.m, self.c)
        with self.assertRaisesRegex(ValueError, "model rejected"):
            validate_model(model, bank, self.c)

    def test_evaluation_empty_is_not_run_and_demo_never_improvement(self):
        empty = deepcopy(self.l)
        empty["triplets"] = []
        report = evaluate(self.m, self.i, empty)
        self.assertTrue(all(x["status"] == "NOT RUN" for x in report["aspects"].values()))
        model = train(self.m, self.i, self.l, self.c, allow_synthetic=True)
        report = evaluate(self.m, self.i, self.l, self.c, model, allow_synthetic=True)
        self.assertEqual(report["improvement"], "NOT ESTABLISHED")
        self.assertEqual(set(report["cases"]), set(CASES))

    def test_evaluation_rejects_changed_labels(self):
        model = train(self.m, self.i, self.l, self.c, allow_synthetic=True)
        self.l["triplets"][-1]["positive"], self.l["triplets"][-1]["negative"] = "test2", "test1"
        with self.assertRaisesRegex(ValueError, "provenance"):
            evaluate(self.m, self.i, self.l, self.c, model, allow_synthetic=True)

    def test_shared_candidates_reduce_independent_sample_count(self):
        t = deepcopy(self.l["triplets"][-3])
        t.update(anchor="test1", positive="test0", negative="test2")
        self.l["triplets"].append(t)
        report = evaluate(self.m, self.i, self.l)
        self.assertEqual(report["aspects"]["rhythm"]["n"], 2)
        self.assertEqual(report["aspects"]["rhythm"]["artist_groups"], 1)

    def test_equal_models_cannot_establish_improvement(self):
        observations = [(str(i), .5, .5) for i in range(5)]
        result = summary(observations)
        self.assertEqual(result["paired_delta_ci95"], [0., 0.])
        self.assertEqual(result["delta"], 0.)

    def test_cluster_bootstrap_and_no_unsupported_confidence(self):
        one = summary([("a", 0., 1.)] * 100)
        self.assertIsNone(one["paired_delta_ci95"])
        many = summary([(str(i), 0., 1.) for i in range(5)])
        self.assertEqual(many["paired_delta_ci95"], [1., 1.])


class LocalAudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        m, _, _, _ = fixture()
        cls.manifest = {**m, "tracks": m["tracks"][:3]}
        evidence = cls.root / "evidence.txt"
        evidence.write_text("Test-generated waveforms; CC0; not real musical labels")
        sr = 16000
        for i, t in enumerate(cls.manifest["tracks"]):
            # Equal tempo, different harmonic envelope; no real artist/audio.
            times = np.arange(sr * 10) / sr
            envelope = np.exp(-20 * (times % .5))
            y = .3 * envelope * (np.sin(2 * np.pi * (220 + 220 * i) * times) +
                                  .3 * np.sin(2 * np.pi * (440 + 440 * i) * times))
            path = cls.root / (t["id"] + ".wav")
            sf.write(path, y, sr)
            t.update(path=str(path), sha256=file_hash(path))
            t["rights"].update(evidence_path=str(evidence), evidence_sha256=file_hash(evidence))
        cls.index = build_index(cls.manifest)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_shapes_repeatability_and_real_signal_timbre(self):
        self.assertEqual(self.index["tracks"][0], extract(self.manifest["tracks"][0]))
        self.assertEqual(len(self.index["tracks"][0]["lab27"]), 27)
        self.assertNotEqual(self.index["tracks"][0]["vectors"]["timbre"],
                            self.index["tracks"][1]["vectors"]["timbre"])

    def test_local_search_no_self_and_deterministic(self):
        query = Path(self.manifest["tracks"][0]["path"])
        a = search(query, self.manifest, self.index)
        b = search(query, self.manifest, self.index)
        self.assertEqual(a, b)
        self.assertEqual(len(a["results"]), 2)
        self.assertNotIn("train0", [t["id"] for t in a["results"]])

    def test_file_change_and_evidence_change_are_rejected(self):
        missing = deepcopy(self.manifest)
        missing["tracks"][0]["path"] = str(self.root / "missing.wav")
        with self.assertRaisesRegex(ValueError, "Expected a local audio"):
            validate_manifest(missing, verify_files=True)
        m = deepcopy(self.manifest)
        m["tracks"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "Audio hash changed"):
            validate_manifest(m, verify_files=True)
        m = deepcopy(self.manifest)
        m["tracks"][0]["rights"]["evidence_sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "Rights evidence changed"):
            validate_manifest(m, verify_files=True)

    def test_atomic_create_only_private_and_finite(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "result.json"
            write_new(p, {"v": 1})
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_new(p, {"v": 2})
            self.assertEqual(read_json(p), {"v": 1})
            with self.assertRaises(ValueError):
                write_new(p, {"v": float("nan")})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_cli_success_error_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, index = Path(directory) / "m.json", Path(directory) / "i.json"
            write_new(manifest, self.manifest)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["index", "--manifest", str(manifest), "--out", str(index)]), 0)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["search", self.manifest["tracks"][0]["path"], "--manifest", str(manifest),
                                       "--index", str(index), "--top", "1"]), 0)
            self.assertEqual(len(json.loads(out.getvalue())["results"]), 1)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["index", "--manifest", str(manifest), "--out", str(index)]), 2)

    def test_unknown_query_needs_reviewed_rights(self):
        m = deepcopy(self.manifest)
        m["tracks"] = m["tracks"][1:]
        index = build_index(m)
        path = self.manifest["tracks"][0]["path"]
        with self.assertRaisesRegex(ValueError, "query-manifest"):
            search(path, m, index)
        qm = {**self.manifest, "tracks": self.manifest["tracks"][:1]}
        self.assertEqual(len(search(path, m, index, query_manifest=qm)["results"]), 2)

    def test_controlled_rhythm_timbre_energy_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            sr = 16000
            times = np.arange(sr * 10) / sr
            rows = {}
            # These genre strings are arbitrary test metadata, never real labels.
            specs = [("anchor", 120, 220, .3, "A"), ("other_genre", 120, 2200, .3, "B"),
                     ("same_genre", 90, 220, .3, "A"), ("quiet", 120, 220, .03, "A")]
            for tid, bpm, hz, gain, genre in specs:
                envelope = np.exp(-25 * (times % (60 / bpm)))
                signal = gain * envelope * np.sin(2 * np.pi * hz * times)
                path = Path(directory) / (tid + ".wav")
                sf.write(path, signal, sr)
                t = {"id": tid, "sha256": file_hash(path), "path": str(path), "start": 0, "seconds": 10, "genre": genre}
                rows[tid] = extract(t)
            bank = {tid: {k: np.asarray(t["vectors"][k]) / 3 for k in ASPECTS} for tid, t in rows.items()}
            same_rhythm = distances("anchor", "other_genre", rows, bank)
            changed_rhythm = distances("anchor", "same_genre", rows, bank)
            quieter = distances("anchor", "quiet", rows, bank)
            self.assertLess(same_rhythm["rhythm"], changed_rhythm["rhythm"])
            self.assertGreater(same_rhythm["timbre"], quieter["timbre"])
            self.assertGreater(quieter["energy"], same_rhythm["energy"])

    def test_silence_and_short_decode_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "silence.wav"
            sf.write(p, np.zeros(16000 * 10), 16000)
            t = {"id": "silent", "path": str(p), "sha256": file_hash(p), "start": 0, "seconds": 10}
            with self.assertRaisesRegex(ValueError, "Silent"):
                extract(t)
            t["start"] = 1
            with self.assertRaisesRegex(ValueError, "Short"):
                extract(t)

    def test_remote_never_falls_back_or_fetches(self):
        with self.assertRaisesRegex(ValueError, "remote execution"):
            extract_embeddings(self.manifest, self.root, {})

    def test_snapshot_hash_and_unlisted_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("config.json", "preprocessor_config.json", "model.safetensors"):
                (root / name).write_text("test stub, never loaded")
            receipt = {"id": ENCODER_ID, "weights_license": "CC-BY-NC-4.0", "reviewed_code": True,
                       "revision": "a" * 40, "files": {p.name: file_hash(p) for p in root.iterdir()}}
            self.assertEqual(check_snapshot(root, receipt), root)
            (root / "unreviewed.py").write_text("raise RuntimeError()")
            with self.assertRaisesRegex(ValueError, "Unlisted"):
                check_snapshot(root, receipt)


if __name__ == "__main__":
    unittest.main()
