import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
from listening_study.analysis import analyze
from listening_study.collection import Collection, CONSENT, demo_config
from listening_study.common import digest, read_json
from listening_study.demo import build_demo

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
        out = Path(self.tmp.name) / "export"
        self.assertEqual(self.store.export(out), {"in_progress": 1, "complete": 1})
        result = analyze(self.study, [read_json(p) for p in out.glob("*.json")], draws=200)
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
        out = Path(self.tmp.name) / "export"
        self.assertEqual(self.store.export(out), {"withdrawn": 1})
        self.assertEqual(list(out.iterdir()), [])
        self.assertNotIn(state["response"]["participant_id"].encode(), self.path.read_bytes())
    def test_partial_expiry_and_absolute_retention(self):
        token, state = self.start()
        with self.store.db() as db:
            db.execute("UPDATE sessions SET day=?", (str(date.today() - timedelta(days=7)),))
        self.assertEqual(self.store.state(token)["status"], "expired")
        self.assertNotIn(state["response"]["participant_id"].encode(), self.path.read_bytes())
        with patch("listening_study.collection.date") as clock:
            clock.today.return_value = date.fromisoformat(self.config["delete_on"])
            clock.fromisoformat.side_effect = date.fromisoformat
            self.store.purge()
            with self.assertRaises(ValueError): self.start()
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
    def test_config_binding_and_closed_intake(self):
        with self.assertRaisesRegex(ValueError, "another"):
            Collection(self.study, self.path, {**self.config, "contact": "A different operator contact"})
        with patch("listening_study.collection.date") as clock:
            clock.today.return_value = date.fromisoformat(self.config["intake_closes_on"])
            clock.fromisoformat.side_effect = date.fromisoformat
            with self.assertRaisesRegex(ValueError, "closed"): self.start()
    def test_public_rights_not_inferred(self):
        study = copy.deepcopy(self.study); study.update(demo=False, phase="pilot")
        study["sha256"] = digest({k: v for k, v in study.items() if k != "sha256"})
        with self.assertRaisesRegex(ValueError, "public reproduction"):
            Collection(study, Path(self.tmp.name) / "real.sqlite", self.config)
