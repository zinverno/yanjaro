import copy
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import Mock, patch
from listening_study.collection import Collection, CONSENT, demo_config
from listening_study.common import digest, read_json
from listening_study.demo import build_demo
from listening_study.server import QuietServer

CONSENT_BODY = {"consent": True, "consent_version": CONSENT}

class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.study = build_demo(Path(cls.fixture.name) / "demo")
    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "study.sqlite"
        self.config = demo_config()
        self.store = Collection(self.study, self.path, self.config)
    def start(self):
        return self.store.start(None, CONSENT_BODY)
    def answer(self, token, state, i=0, choice="skip"):
        return self.store.answer(token, {"index": i, "answer": {"trial_id": state["bundle"]["trials"][i]["id"],
                                "choice": choice, "heard": dict.fromkeys(("source", "left", "right"), choice != "skip")}})
    def finish(self):
        token, state = self.start()
        for i in range(len(state["bundle"]["trials"])):
            state = self.answer(token, state, i)
        return token, self.store.complete(token)
    def test_consent_no_pii(self):
        for data in ({}, {**CONSENT_BODY, "consent": False}, {**CONSENT_BODY, "consent": 1},
                     {**CONSENT_BODY, "email": "unwanted"}, {**CONSENT_BODY, "consent_version": "old"}):
            with self.assertRaises(ValueError): self.store.start(None, data)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
    def test_concurrent_balanced_seats_and_capacity(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            states = list(executor.map(lambda _: self.start()[1], range(32)))
        self.assertEqual({(s["bundle"]["prompt_id"], s["bundle"]["slot"]) for s in states},
                         {(p, i) for p in ("next", "similarity") for i in range(16)})
        with self.assertRaisesRegex(ValueError, "occupied"): self.start()
    def test_start_idempotent(self):
        token, state = self.start()
        _, again = self.store.start(token, CONSENT_BODY)
        self.assertEqual(state["response"], again["response"])
        self.assertNotIn("recovery_code", again)
    def test_capacity_closure_survives_late_withdrawal(self):
        for _ in range(32):
            token, _ = self.finish()
        self.store.withdraw(token)
        with self.assertRaisesRegex(ValueError, "closed"):
            self.start()
        restarted = Collection(self.study, self.path, self.config)
        with self.assertRaisesRegex(ValueError, "closed"):
            restarted.start(None, CONSENT_BODY)
    def test_shortlist_is_not_fake_measured_or_approved_audio(self):
        candidates = read_json(Path(__file__).parent.parent / "examples/real-candidates.v1.json")
        self.assertEqual(candidates["status"], "REVIEW_ONLY_NOT_A_STUDY")
        self.assertEqual(candidates["pool_revision"], 2)
        self.assertGreaterEqual(len(candidates["tracks"]), 36)
        self.assertLessEqual(len(candidates["tracks"]), 60)
        self.assertGreaterEqual(len({t["creator_id"] for t in candidates["tracks"]}), 8)
        self.assertEqual(len({t["id"] for t in candidates["tracks"]}), len(candidates["tracks"]))
        for track in candidates["tracks"]:
            self.assertIsNone(track["features"])
            self.assertIsNone(track["local_file_sha256"])
            self.assertIsNone(track["confirmed_recording_license"])
            self.assertIsNone(track["excerpt_start"])
            self.assertIsNone(track["excerpt_seconds"])
            self.assertFalse(track["rights_reviewed"])
            self.assertFalse(track["public_release_approved"])
            self.assertFalse(track["review"]["listened"])
            self.assertIn(track["publication_status"], candidates["status_definitions"])
            self.assertTrue(track["license_evidence"])
            self.assertTrue(track["recording_locator"])
            for kind in ("genre", "instrument"):
                if track[kind]:
                    self.assertTrue(track[kind + "_source"]["url"].startswith("https://"))
                    self.assertTrue(track[kind + "_source"]["scope"])
                else:
                    self.assertIsNone(track[kind + "_source"])
            if track["publication_status"] == "CONFLICTING_STATEMENTS":
                self.assertGreaterEqual(len({lic for e in track["license_evidence"] for lic in e["observed_licenses"]}
                                           | {track["declared_license"]}), 2)
            if track["publication_status"] == "CONFIRMED_RECORD_PAGE":
                self.assertTrue(any(e["access"] == "page_read" and track["declared_license"] in e["observed_licenses"]
                                    for e in track["license_evidence"]))
    def test_review_sheet_preserves_ids_and_separates_hints_from_observations(self):
        examples = Path(__file__).parent.parent / "examples"
        tracks = read_json(examples / "real-candidates.v1.json")["tracks"]
        with (examples / "listening-review.v1.csv").open(newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual([t["id"] for t in tracks], [r["id"] for r in rows])
        originals = {f"{prefix}{n:02}" for prefix in ("h", "j") for n in range(1, 9)}
        originals |= {f"m{n:02}" for n in (1, 2, 3, 4, 5, 6, 12, 14)}
        self.assertEqual({t["id"] for t in tracks[:24]}, originals)
        for track, row in zip(tracks, rows):
            for key in ("artist", "title", "source", "creator_id", "publication_status", "declared_license"):
                self.assertEqual(track[key], row[key])
            self.assertEqual(row["confirmed_recording_license"], "UNKNOWN")
            self.assertEqual(row["instrument_hint"], "; ".join(track["instrument"]) or "UNKNOWN")
            for key in ("listen_status", "keep", "heard_instruments", "heard_genre", "bpm_manual", "start_seconds",
                        "duration_seconds", "master_sha256", "applicable_license", "analysis_permission",
                        "excerpt_permission", "public_playback_permission", "delayed_attribution_permission"):
                self.assertEqual(row[key], "", f"unreviewed {track['id']} must not prefill {key}")
    def test_restart_recovery_and_foreign_session(self):
        token, state = self.start()
        saved = self.answer(token, state)
        restarted = Collection(self.study, self.path, self.config)
        self.assertEqual(saved, restarted.state(token))
        with self.assertRaises(ValueError): restarted.state(secrets.token_urlsafe(32))
        new, restored = restarted.resume(state["recovery_code"])
        self.assertEqual(restored, saved)
        self.assertEqual(restarted.state(new), saved)
        with self.assertRaises(ValueError): restarted.state(token)
    def test_database_minimization(self):
        token, state = self.start()
        raw = self.path.read_bytes()
        self.assertNotIn(token.encode(), raw)
        self.assertNotIn(state["recovery_code"].encode(), raw)
        with self.store.db() as db:
            fields = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
        self.assertEqual(fields, {"id", "token", "recovery", "prompt", "slot", "day", "consent", "status", "response"})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
    def test_retries_conflicts_order_and_validation(self):
        token, state = self.start()
        saved = self.answer(token, state)
        self.assertEqual(saved, self.answer(token, state))
        with self.assertRaises(ValueError): self.answer(token, state, choice="left")
        with self.assertRaises(ValueError): self.answer(token, state, 2)
        for data in ({"index": True, "answer": {}}, {"index": 1, "answer": {}, "name": "bad"},
                     {"index": 1, "answer": {"trial_id": state["bundle"]["trials"][1]["id"], "choice": "left", "heard": dict.fromkeys(("source", "left", "right"), False)}}):
            with self.assertRaises(ValueError): self.store.answer(token, data)
        self.assertEqual(saved, self.store.state(token))
    def test_completion_export_and_analysis(self):
        t, _ = self.start()
        with self.assertRaises(ValueError): self.store.complete(t)
        token, state = self.finish()
        self.assertEqual(self.store.complete(token), state)
        with self.assertRaises(ValueError): self.answer(token, state)
        result = self.store.report(draws=200)
        self.assertEqual(result["collection_counts"], {"in_progress": 1, "complete": 1})
        self.assertEqual(sum(r["participants"] for r in result["results_by_prompt"].values()), 1)
        self.assertIn("surveycircle_code", state)
        self.assertIn("credits", state)
    def test_withdraw_erases_and_reuses_seat_without_reentry(self):
        token, state = self.start()
        self.answer(token, state)
        deleted = self.store.withdraw(token)
        self.assertEqual(deleted, self.store.withdraw(token))
        self.assertEqual(deleted["status"], "withdrawn")
        self.assertNotIn("response", deleted)
        self.assertNotIn(state["response"]["participant_id"].encode(), self.path.read_bytes())
        self.assertEqual(self.store.start(token, CONSENT_BODY)[1], deleted)
        self.assertEqual(self.start()[1]["bundle"], state["bundle"])
        with self.assertRaises(ValueError): self.answer(token, state)
    def test_completed_withdrawal_removed_from_export(self):
        token, state = self.finish()
        self.store.withdraw(token)
        result = self.store.report(draws=200)
        self.assertEqual(result["collection_counts"], {"withdrawn": 1})
        self.assertEqual(sum(r["participants"] for r in result["results_by_prompt"].values()), 0)
        self.assertNotIn(state["response"]["participant_id"].encode(), self.path.read_bytes())
    def test_partial_expiry_and_absolute_retention(self):
        token, state = self.start()
        with self.store.db() as db:
            db.execute("UPDATE sessions SET day=?", (str(date.today() - timedelta(days=7)),))
        self.assertEqual(self.store.state(token)["status"], "expired")
        self.assertNotIn(state["response"]["participant_id"].encode(), self.path.read_bytes())
        with patch("listening_study.collection.today_utc") as clock:
            clock.return_value = date.fromisoformat(self.config["delete_on"])
            self.store.purge()
            with self.assertRaises(ValueError): self.start()
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
    def test_expiry_survives_rejected_request(self):
        token, _ = self.start()
        with patch("listening_study.collection.today_utc", return_value=date.fromisoformat(self.config["delete_on"])):
            with self.assertRaises(ValueError):
                self.store.state(token)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
    def test_idle_server_runs_retention_without_requests(self):
        server = object.__new__(QuietServer)
        server.collector = Mock()
        with patch("listening_study.server.time.monotonic", return_value=100):
            server.service_actions()
            server.service_actions()
        self.assertEqual(server.collector.purge.call_count, 1)
        with patch("listening_study.server.time.monotonic", return_value=161):
            server.service_actions()
        self.assertEqual(server.collector.purge.call_count, 2)
    def test_config_binding_and_closed_intake(self):
        with self.assertRaisesRegex(ValueError, "another"):
            Collection(self.study, self.path, {**self.config, "contact": "A different operator contact"})
        with patch("listening_study.collection.today_utc") as clock:
            clock.return_value = date.fromisoformat(self.config["intake_closes_on"])
            with self.assertRaisesRegex(ValueError, "closed"): self.start()
    def test_public_rights_not_inferred(self):
        study = copy.deepcopy(self.study); study.update(demo=False, phase="pilot")
        study["sha256"] = digest({k: v for k, v in study.items() if k != "sha256"})
        with self.assertRaisesRegex(ValueError, "public reproduction"):
            Collection(study, Path(self.tmp.name) / "real.sqlite", self.config)
    def test_maintenance_does_not_create_an_empty_database_on_path_typo(self):
        from listening_study.__main__ import main
        missing = Path(self.tmp.name) / "missing.sqlite"
        for command in ("analyze-collected", "purge-collected"):
            argv = ["study", command, "study.json", str(missing), "config.json"]
            if command == "analyze-collected": argv.append("out.json")
            with patch("sys.argv", argv), patch("sys.stderr"):
                self.assertEqual(main(), 2)
            self.assertFalse(missing.exists())
