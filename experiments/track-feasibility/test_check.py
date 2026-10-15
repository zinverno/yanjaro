import copy
import tempfile
import unittest
from pathlib import Path

import check


class FeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.rows = check.sample()
        self.evidence = check.read_json(check.ROOT / "observations.json")
        self.scan = check.read_json(check.ROOT / "jamendo-scan.json")

    def test_replay_matches_published_results(self):
        result = check.replay(self.rows, self.evidence, self.scan)
        self.assertEqual(result, check.read_json(check.ROOT / "results.json"))
        self.assertEqual(result["summary"]["sample_size"], 30)
        self.assertEqual(result["summary"]["acoustic_vectors"], 0)

    def test_release_and_external_isrc_do_not_promote_recording(self):
        result = check.replay(self.rows, self.evidence, self.scan)["tracks"][6]
        self.assertTrue(result["identity_checks"]["release_crosswalk_supported"])
        self.assertEqual(result["external_candidates"][1]["isrc"], "FR59R2630848")
        self.assertIsNone(result["yandex_metadata"]["isrc"]["value"])
        self.assertFalse(result["exact_recording_match"])
        self.assertIsNone(result["acoustic_vector"])

    def test_tampering_missing_rows_and_fake_vectors_rejected(self):
        for mutation in ("missing", "vector", "namespace", "promotion", "album"):
            evidence = copy.deepcopy(self.evidence)
            if mutation == "missing":
                evidence["tracks"].pop()
            elif mutation == "vector":
                evidence["tracks"][0]["acoustic_vector"] = [0.0] * 8
            elif mutation == "namespace":
                evidence["tracks"][6]["external_candidates"][1]["namespace"] = "yambda_item"
            elif mutation == "promotion":
                evidence["tracks"][6]["external_candidates"][1]["identity"] = "EXACT_RECORDING"
            else:
                evidence["tracks"][6]["external_candidates"][0]["yandex_album_id"] = "999"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                check.replay(self.rows, evidence, self.scan)

    def test_sample_hash_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_bytes((check.ROOT / "sample.json").read_bytes() + b" ")
            with self.assertRaises(ValueError):
                check.sample(path)

    def test_title_collision_quotes_and_bad_rows(self):
        rows = [{"yandex_track_id": "1", "discovery_claim": {"artist": "Korn", "title": "Blind"}}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.meta.tsv"
            path.write_text(
                'TRACK_ID\tARTIST_NAME\tTRACK_NAME\tALBUM_NAME\tURL\n'
                'track_1\tOther\tBlind\t"literal quote\thttps://example.org/1\n'
                'track_2\tKORN\tblind\tLive\thttps://example.org/2\n'
                'track_3\tBroken\tBlind\tExtra\tcolumn\thttps://example.org/3\n',
                encoding="utf-8",
            )
            result = check.scan_jamendo(path, rows)
        self.assertEqual(result["rows_scanned"], 2)
        self.assertEqual(len(result["rejected_rows"]), 1)
        self.assertEqual(result["matches"]["1"]["title_only_count"], 2)
        candidates = result["matches"]["1"]["artist_title_candidates"]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["identity"], "CANDIDATE_ONLY")

    def test_empty_table_is_not_evidence_of_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.tsv"
            path.write_text('TRACK_ID\tARTIST_NAME\tTRACK_NAME\tALBUM_NAME\tURL\n')
            with self.assertRaises(ValueError):
                check.scan_jamendo(path, self.rows)


if __name__ == "__main__":
    unittest.main()
