import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import soundfile as sf
from listening_study.common import read_json
from listening_study.demo import build_demo
from listening_study.design import screen, freeze
from listening_study.quality import inspect_audio, excerpt_window
from listening_study.reviewer import export_review, provisional_trials, review_bundle


class QualityTests(unittest.TestCase):
    def test_fixed_windows_no_padding_or_score_search(self):
        self.assertEqual(excerpt_window(45)["start"], 30)
        self.assertEqual(excerpt_window(22)["start"], 3.5)
        self.assertEqual(excerpt_window(15)["start"], 0)
        for duration in (14.99, float("nan"), 4000):
            with self.assertRaises(ValueError): excerpt_window(duration)

    def test_full_decode_detects_silence_clipping_and_stereo_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.wav"
            y = np.ones((16000, 2)); y[:8000] = 0; y[8000:, 1] = -1
            sf.write(path, y, 8000, subtype="FLOAT")
            qc = inspect_audio(path)
            self.assertEqual(qc["frames"], 16000)
            self.assertEqual(qc["near_full_scale_sample_fraction"], .5)
            self.assertEqual(qc["silent_20ms_fraction"], .5)
            self.assertEqual(qc["mono_rms_dbfs"], -160)
            self.assertIsNone(qc["audible_artifacts"])
            y[3, 0] = np.nan; sf.write(path, y, 8000, subtype="FLOAT")
            with self.assertRaisesRegex(ValueError, "Nonfinite"): inspect_audio(path)


class ReviewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build_demo(cls.root / "demo")
        cls.catalog = read_json(cls.root / "demo/prepared/catalog.json")
        cls.pool = {"tracks": [{"id": t["id"], "title": "</script><img src=x>", "artist": "Synthetic",
                                "private_path": "/private/never-embed"} for t in cls.catalog["tracks"]]}

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_strict_preview_keeps_recordings_creators_and_roles_separate(self):
        result = provisional_trials(self.catalog, screen(self.catalog)["pairs"])
        self.assertTrue(result["options"])
        used, roles, artists = set(), {}, {}
        tracks = {t["id"]: t for t in self.catalog["tracks"]}
        for trial in result["disjoint_preview"]:
            self.assertEqual(trial["status"], "PROVISIONAL")
            ids = [trial[k] for k in ("source", "first", "second")]
            self.assertFalse(used.intersection(ids)); used.update(ids)
            creators = [tracks[i]["artist_id"] for i in ids]
            self.assertEqual(len(set(creators)), 3)
            for artist in creators: artists[artist] = artists.get(artist, 0) + 1
            if trial["kind"] == "primary":
                for artist, sign in zip(creators[1:], (1, -1)): roles[artist] = roles.get(artist, 0) + sign
        self.assertTrue(all(v <= 4 for v in artists.values()))
        self.assertTrue(all(abs(v) <= 1 for v in roles.values()))
        self.assertLessEqual(sum(t["kind"] == "primary" for t in result["disjoint_preview"]), 6)
        self.assertLessEqual(sum(t["kind"] == "control" for t in result["disjoint_preview"]), 2)

    def test_unknown_tags_produce_zero_options_without_threshold_relaxation(self):
        catalog = copy.deepcopy(self.catalog)
        for t in catalog["tracks"]: t["instrument"] = []
        self.assertEqual(review_bundle(catalog, self.pool)["trials"]["options"], [])

    def test_output_requires_permission_private_destination_and_unchanged_clips(self):
        real = copy.deepcopy(self.catalog); real["demo"] = False
        with self.assertRaisesRegex(ValueError, "allow-real-audio"):
            export_review(real, self.pool, self.root / "real")
        with tempfile.TemporaryDirectory() as repo:
            git = Path(repo) / ".git"; git.mkdir(); (git / "HEAD").write_text("ref: refs/heads/main\n")
            with self.assertRaisesRegex(ValueError, "outside Git"):
                export_review(real, self.pool, Path(repo) / "review", allow_real_audio=True)
        real["tracks"][0]["clip_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "Changed review clip"):
            export_review(real, self.pool, self.root / "changed", allow_real_audio=True)

    def test_two_pages_do_not_include_private_paths_or_create_approval(self):
        out = self.root / "review"
        bundle = export_review(self.catalog, self.pool, out)
        self.assertNotIn("/private/never-embed", json.dumps(bundle))
        self.assertNotIn(str(self.root), json.dumps(bundle))
        for reviewer in ("reviewer-1", "reviewer-2"):
            html = (out / (reviewer + ".html")).read_text()
            self.assertIn('"reviewer": "' + reviewer + '"', html)
            self.assertIn('media-src data:', html)
            self.assertNotIn('</script><img src=x>', html)
            self.assertIn('data:audio/wav;base64,', html)
            self.assertEqual((out / (reviewer + ".html")).stat().st_mode & 0o777, 0o600)
        review = screen(self.catalog)
        review["trials"] = [{"id": "r" + str(i), **{k:t[k] for k in ("kind","source","first","second")}}
                            for i,t in enumerate(bundle["trials"]["disjoint_preview"])]
        with self.assertRaisesRegex(ValueError, "Manual"):
            freeze(self.catalog, review, study_id="unapproved", seed=1, phase="demo")
        with self.assertRaisesRegex(ValueError, "must be new"):
            export_review(self.catalog, self.pool, out)
