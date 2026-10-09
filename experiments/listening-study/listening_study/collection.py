"""Small, single-study SQLite collector; no identities, network calls or request logs."""
from contextlib import contextmanager
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import random
import re
import secrets
import sqlite3
import uuid

from .analysis import validate_answers, validate_response
from .common import digest, require, write_new
from .design import public_bundle, schedule, validate_study

CONSENT = "collection-consent-v1"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def token_hash(token):
    require(isinstance(token, str) and TOKEN.fullmatch(token), "Invalid session code")
    return hashlib.sha256(token.encode()).hexdigest()


def demo_config():
    today = date.today()
    return {"consent_version": CONSENT, "capacity": 32, "contact": "Локальный DEMO: исследователь за этим компьютером",
            "intake_closes_on": str(today + timedelta(days=30)), "delete_on": str(today + timedelta(days=90)),
            "surveycircle_code": "DEMO — не код SurveyCircle", "public_origin": None}


class Collection:
    def __init__(self, study, path, config):
        validate_study(study)
        require(set(config) == set(demo_config()) and config["consent_version"] == CONSENT, "Invalid collection config")
        require(type(config["capacity"]) is int and config["capacity"] == 4 * len(study["trials"]),
                "Capacity must be a full 2N schedule block per wording")
        require(8 <= config["capacity"] <= 128, "Capacity out of range")
        require(isinstance(config["contact"], str) and 10 <= len(config["contact"]) <= 250, "Research contact required")
        require(isinstance(config["surveycircle_code"], str) and len(config["surveycircle_code"]) <= 200, "Invalid reward code")
        close, delete = (date.fromisoformat(config[k]) for k in ("intake_closes_on", "delete_on"))
        require(close < delete <= close + timedelta(days=90), "Invalid retention dates")
        if not study["demo"]:
            for track in study["tracks"].values():
                require(all(track["rights"].get(k) is True for k in ("public_reproduction", "delayed_attribution")),
                        "Real collection needs reviewed public reproduction and delayed attribution rights")
        self.study, self.config, self.path = study, config, Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(not self.path.is_symlink(), "Database must not be a symlink")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        require(self.path.stat().st_mode & 0o077 == 0, "Database must be private (0600)")
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), digest TEXT NOT NULL)")
            expected = digest({"study": study["sha256"], "config": config, "storage": "collection-v1"})
            db.execute("INSERT OR IGNORE INTO meta VALUES (1, ?)", (expected,))
            require(db.execute("SELECT digest FROM meta").fetchone()[0] == expected, "Database belongs to another study/config")
            db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, recovery TEXT UNIQUE NOT NULL,
                prompt TEXT NOT NULL, slot INTEGER NOT NULL, day TEXT NOT NULL,
                consent TEXT NOT NULL, status TEXT NOT NULL, response TEXT)""")
        self.deck = [(p, i) for i in range(config["capacity"] // 2) for p in ("next", "similarity")]
        # Wording in blocks of two; fixed assignment seats survive restarts and are reused only after withdrawal/expiry.
        rng = random.Random(f"{study['seed']}:collection-v1")
        for i in range(0, len(self.deck), 2):
            if rng.getrandbits(1):
                self.deck[i:i+2] = reversed(self.deck[i:i+2])

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def purge_in(self, db, today):
        if today >= date.fromisoformat(self.config["delete_on"]):
            db.execute("DELETE FROM sessions")
        else:
            db.execute("UPDATE sessions SET response=NULL, status='expired' WHERE status='in_progress' AND day <= ?",
                       (str(today - timedelta(days=7)),))

    def purge(self):
        with self.db() as db:
            self.purge_in(db, date.today())

    def find(self, db, token):
        row = db.execute("SELECT * FROM sessions WHERE token=?", (token_hash(token),)).fetchone()
        require(row is not None, "Session unavailable")
        return row

    def view(self, row):
        result = {"status": row["status"]}
        if row["response"]:
            result.update(bundle=public_bundle(self.study, row["slot"], row["prompt"]), response=json.loads(row["response"]))
        if row["status"] in ("complete", "withdrawn"):
            result["credits"] = [t["rights"]["attribution"] for t in self.study["tracks"].values()]
        if row["status"] == "complete":
            result["surveycircle_code"] = self.config["surveycircle_code"]
        return result

    def start(self, token, consent):
        require(consent == {"consent": True, "consent_version": CONSENT} and type(consent["consent"]) is bool,
                "Explicit current consent required")
        today = date.today()
        with self.db() as db:
            self.purge_in(db, today)
            if token:
                row = db.execute("SELECT * FROM sessions WHERE token=?", (token_hash(token),)).fetchone()
                if row:
                    return token, self.view(row)
            require(today < date.fromisoformat(self.config["intake_closes_on"]), "Recruitment closed")
            used = {(r[0], r[1]) for r in db.execute("SELECT prompt,slot FROM sessions WHERE status IN ('in_progress','complete')")}
            seat = next((s for s in self.deck if s not in used), None)
            require(seat is not None, "All study places are occupied")
            # Bounded storage even if someone clears cookies repeatedly. No IP or device fingerprint.
            require(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] < 256, "Intake limit reached; contact researcher")
            prompt, slot = seat
            token, recovery = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            bundle = public_bundle(self.study, slot, prompt)
            response = {k: bundle[k] for k in ("schema", "study_id", "study_sha256", "demo", "phase", "slot", "prompt_id")}
            response.update(participant_id=str(uuid.uuid4()), status="in_progress", answers=[])
            db.execute("INSERT INTO sessions(token,recovery,prompt,slot,day,consent,status,response) VALUES(?,?,?,?,?,?,?,?)",
                       (token_hash(token), token_hash(recovery), prompt, slot, str(today), CONSENT, "in_progress", json.dumps(response)))
            return token, {**self.view(self.find(db, token)), "recovery_code": recovery}

    def state(self, token):
        with self.db() as db:
            self.purge_in(db, date.today())
            return self.view(self.find(db, token))

    def resume(self, code):
        with self.db() as db:
            self.purge_in(db, date.today())
            row = db.execute("SELECT * FROM sessions WHERE recovery=?", (token_hash(code),)).fetchone()
            require(row is not None, "Recovery code unavailable")
            token = secrets.token_urlsafe(32)
            db.execute("UPDATE sessions SET token=? WHERE id=?", (token_hash(token), row["id"]))
            return token, self.view(row)

    def answer(self, token, payload):
        require(isinstance(payload, dict) and set(payload) == {"index", "answer"} and type(payload["index"]) is int,
                "Unexpected answer fields")
        with self.db() as db:
            self.purge_in(db, date.today())
            row = self.find(db, token)
            require(row["status"] == "in_progress", "Session is closed")
            response = json.loads(row["response"])
            answers, index = response["answers"], payload["index"]
            if 0 <= index < len(answers):
                require(answers[index] == payload["answer"], "Conflicting retry; reload saved progress")
            else:
                require(index == len(answers), "Out-of-order answer")
                answers.append(payload["answer"])
                validate_answers(answers, schedule(self.study, row["slot"], row["prompt"]))
                db.execute("UPDATE sessions SET response=? WHERE id=?", (json.dumps(response), row["id"]))
            return self.view(self.find(db, token))

    def complete(self, token):
        with self.db() as db:
            self.purge_in(db, date.today())
            row = self.find(db, token)
            require(row["status"] in ("in_progress", "complete"), "Session is closed")
            response = json.loads(row["response"])
            response["status"] = "complete"
            validate_response(response, self.study)
            db.execute("UPDATE sessions SET status='complete',response=? WHERE id=?", (json.dumps(response), row["id"]))
            return self.view(self.find(db, token))

    def withdraw(self, token):
        with self.db() as db:
            self.purge_in(db, date.today())
            row = self.find(db, token)
            db.execute("UPDATE sessions SET status='withdrawn',response=NULL WHERE id=?", (row["id"],))
            return self.view(self.find(db, token))

    def export(self, out):
        out = Path(out)
        out.mkdir(mode=0o700)  # Fresh private snapshot; no public HTTP/admin endpoint.
        with self.db() as db:
            self.purge_in(db, date.today())
            counts = dict(db.execute("SELECT status,COUNT(*) FROM sessions GROUP BY status").fetchall())
            for row in db.execute("SELECT response FROM sessions WHERE status='complete'"):
                response = json.loads(row[0])
                validate_response(response, self.study)
                write_new(out / (response["participant_id"] + ".json"), response)
        return counts
