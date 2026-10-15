"""Bounded in-memory extraction and private local storage; no network acquisition."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "acoustic-similarity"))
import numpy as np
from acoustic_similarity import acoustic_retrieval as retrieval, features, rhythm_pi

SCHEMA = "yanjaro.personal-acoustic-index.v1"
BASE_HEAD = "35aecde3311fa302e0ac1548d9c53f336ed9c928"
MAX_RECORDS = 1000


class Rejected(Exception):
    """Fixed safe reason code, never a raw system/library exception."""


def require(ok, reason):
    if not ok:
        raise Rejected(reason)


def safe_text(value):
    require(isinstance(value, str) and len(value) <= 256 and
            all(ord(c) >= 32 for c in value) and
            not re.search(r"://|(?i:bearer |oauth|token=)", value), "UNSAFE_METADATA")
    return value


def entry_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value), "INVALID_ENTRY_ID")
    return value


def inside_git(path):
    # Workspace sandboxes may expose empty .git directories; only real repos count.
    return any((p / ".git").is_file() or (p / ".git/HEAD").is_file()
               for p in (Path(path).resolve(), *Path(path).resolve().parents))


def track_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value), "INVALID_TRACK_ID")
    return value


def identity(requested=None, mpris_path=None):
    if requested is not None:
        track_id(requested)
    if mpris_path is not None:
        require(requested is not None and mpris_path ==
                "/org/mpris/MediaPlayer2/track_" + hashlib.sha256(requested.encode()).hexdigest(),
                "MPRIS_ID_MISMATCH")
    return dict(requested_id=requested, observed_id=None, real_id=None,
                observed_id_reason="MPRIS_HASH_ONLY" if mpris_path else "LOCAL_FILE_NO_YANDEX_CONTEXT",
                real_id_reason="NOT_EXPOSED_NO_API_CALL",
                mpris_hash_matches=mpris_path is not None, master_match=False)


def signal_quality(pcm, sr):
    require(type(sr) is int and 8000 <= sr <= 96000 and pcm.ndim == 2 and
            pcm.shape[1] in (1, 2) and 10 * sr <= len(pcm) <= 15 * sr,
            "WINDOW_MUST_BE_10_TO_15_SECONDS")
    require(np.isfinite(pcm).all(), "NONFINITE_PCM")
    peak = float(np.max(np.abs(pcm)))
    require(peak > 1e-5, "NO_SOUND")
    clipped = float(np.mean(np.abs(pcm) >= .999))
    require(peak <= 1.001 and clipped <= .001, "CLIPPING")
    # A conservative integrity gate: a quiet 100 ms block is not indexed as a song.
    blocks = pcm[:len(pcm) // (sr // 10) * (sr // 10)].reshape(-1, sr // 10, pcm.shape[1])
    require(np.min(np.sqrt(np.mean(blocks**2, axis=(1, 2)))) > 1e-5, "SILENCE_OR_DROPOUT")
    return dict(peak=peak, clipped_fraction=clipped, rms=float(np.sqrt(np.mean(pcm**2))),
                native_rate=sr, channels=pcm.shape[1], seconds=len(pcm) / sr,
                dsp_rate=16000, resampling="librosa/soxr_hq to 16000 for DSP; PI uses input rate",
                energy_scope="OBSERVED_PCM_NOT_ORIGINAL_MASTER")


def extract(pcm, sr, key, binding, source, title="", artists=(), capture=None):
    """Consumes/zeroes the supplied writable PCM array even on rejection."""
    mono = dsp_pcm = None
    try:
        observed_at = capture["started_at"] if capture else datetime.now(timezone.utc).isoformat()
        entry_id(key)
        require(source in ("file", "live"), "INVALID_SOURCE")
        safe_text(title)
        require(len(artists) <= 10, "INVALID_ARTISTS")
        artists = [safe_text(a) for a in artists]
        quality = signal_quality(pcm, sr)
        pcm_hash = hashlib.sha256(memoryview(np.ascontiguousarray(pcm)).cast("B")).hexdigest()
        mono = pcm.mean(axis=1, dtype=np.float64)
        pi = rhythm_pi.extract(mono, sr)
        pi.update(id=key, audio_sha256=pcm_hash, recording_group=key, title=title,
                  evidence_sha256=None, sample_rate=sr, start_sample=0, end_sample_exclusive=len(pcm))
        import librosa
        dsp_pcm = librosa.resample(pcm.astype(np.float32).mean(axis=1), orig_sr=sr, target_sr=16000)
        dsp = dict(id=key, sha256=pcm_hash, **features.extract_pcm(dsp_pcm))
        profile = retrieval.combine(pi, dsp)
        record = dict(schema=SCHEMA, observed_at=observed_at,
                      identity=binding, source=source, artists=artists, quality=quality,
                      capture=capture, profile=profile)
        validate_record(record)
        return record
    finally:
        pcm.fill(0)
        if mono is not None:
            mono.fill(0)
        if dsp_pcm is not None:
            dsp_pcm.fill(0)


def validate_record(record):
    require(set(record) == {"schema", "observed_at", "identity", "source", "artists", "quality", "capture", "profile"}
            and record["schema"] == SCHEMA, "INVALID_RECORD_SCHEMA")
    p = record["profile"]
    require(record["source"] in ("file", "live") and len(record["observed_at"]) <= 40 and
            datetime.fromisoformat(record["observed_at"]).tzinfo is not None, "INVALID_OBSERVATION")
    require(set(p) == {"id", "audio_sha256", "recording_group", "title", "evidence_sha256", "sample_rate",
                       "start_sample", "end_sample_exclusive", "feature_schema", "blocks", "missing_reasons",
                       "tempo_hypotheses", "downbeat"}, "UNEXPECTED_PROFILE_FIELDS")
    entry_id(p["id"])
    require(p["recording_group"] == p["id"] and p["evidence_sha256"] is None and
            p["downbeat"] == "UNKNOWN; unused", "INVALID_PROFILE_PROVENANCE")
    safe_text(p["title"])
    require(len(record["artists"]) <= 10, "INVALID_ARTISTS")
    for a in record["artists"]:
        safe_text(a)
    require(record["identity"] == identity(record["identity"]["requested_id"],
            "/org/mpris/MediaPlayer2/track_" + hashlib.sha256(record["identity"]["requested_id"].encode()).hexdigest()
            if record["identity"]["mpris_hash_matches"] else None), "INVALID_IDENTITY")
    if record["source"] == "live":
        require(record["identity"]["mpris_hash_matches"] and record["capture"] is not None and
                p["id"] == "yandex-" + record["identity"]["requested_id"] and p["sample_rate"] == 48000,
                "LIVE_IDENTITY_OR_RATE_MISMATCH")
    else:
        require(record["identity"] == identity() and record["capture"] is None, "FILE_CANNOT_CLAIM_LIVE_IDENTITY")
    require(record["capture"] is None or set(record["capture"]) ==
            {"method", "sample_rate", "player_volume", "sink_input_volume", "sink_volume", "position_start_us",
             "started_at", "stopped_at"},
            "INVALID_CAPTURE_FIELDS")
    require(set(record["quality"]) == {"peak", "clipped_fraction", "rms", "native_rate", "channels", "seconds",
                                      "dsp_rate", "resampling", "energy_scope"}, "INVALID_QUALITY_FIELDS")
    q = record["quality"]
    require(all(type(q[k]) in (int, float) and np.isfinite(q[k]) for k in
                ("peak", "clipped_fraction", "rms", "native_rate", "channels", "seconds", "dsp_rate")) and
            10 <= q["seconds"] <= 15 and q["dsp_rate"] == 16000 and
            q["energy_scope"] == "OBSERVED_PCM_NOT_ORIGINAL_MASTER" and
            q["resampling"] == "librosa/soxr_hq to 16000 for DSP; PI uses input rate", "INVALID_QUALITY_VALUES")
    for candidate in p["tempo_hypotheses"]:
        require(set(candidate) == {"bpm", "ac_score"} and all(type(v) in (int, float) and np.isfinite(v)
                for v in candidate.values()), "INVALID_TEMPO_HYPOTHESES")
    require(set(p["missing_reasons"]) <= set(retrieval.NAMES) and all(v in
            ("PI_ABSTAIN", "NO_QUALIFYING_TEMPO_PEAK", "NO_HISTOGRAM_MASS") for v in p["missing_reasons"].values()),
            "INVALID_MISSING_REASONS")
    if record["capture"] is not None:
        c = record["capture"]
        require(record["source"] == "live" and c["method"] == "libpulse-single-sink-input" and c["sample_rate"] == 48000
                and type(c["position_start_us"]) is int and type(c["player_volume"]) in (int, float)
                and 0 < c["player_volume"] <= 1 and all(type(v) is int and 0 < v <= 131072
                    for v in c["sink_input_volume"] + c["sink_volume"]), "INVALID_CAPTURE_VALUES")
        require(c["started_at"] == record["observed_at"] and len(c["stopped_at"]) <= 40 and
                datetime.fromisoformat(c["stopped_at"]) >= datetime.fromisoformat(c["started_at"]), "INVALID_CAPTURE_TIME")
    retrieval.validate(p)
    require(len(json.dumps(record, allow_nan=False)) < 60000, "RECORD_TOO_LARGE")


def read_file(path, start, seconds):
    import soundfile as sf
    path = Path(path).resolve(strict=True)
    require(path.is_file() and 0 <= start and 10 <= seconds <= 15, "INVALID_LOCAL_WINDOW")
    with sf.SoundFile(path) as audio:
        require(8000 <= audio.samplerate <= 96000 and audio.channels in (1, 2), "UNSUPPORTED_LOCAL_AUDIO")
        sr = audio.samplerate
        audio.seek(round(start * sr))
        pcm = audio.read(round(seconds * sr), dtype="float64", always_2d=True)
    if len(pcm) != round(seconds * sr):
        pcm.fill(0)
        raise Rejected("SHORT_LOCAL_FILE")
    return pcm, sr


class Index:
    def __init__(self, root):
        root = Path(root).absolute()
        require(not inside_git(root), "INDEX_MUST_BE_OUTSIDE_GIT")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = root.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700,
                "INDEX_DIRECTORY_MUST_BE_PRIVATE_0700")
        self.path = root / "index.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            st = os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_nlink == 1 and
                    stat.S_IMODE(st.st_mode) == 0o600, "INDEX_FILE_MUST_BE_PRIVATE_0600")
        finally:
            os.close(fd)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            require(version in (0, 1), "INCOMPATIBLE_INDEX_VERSION")
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            require(tables in ([], [("records",)]), "FOREIGN_DATABASE")
            db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            with db:
                yield db
        finally:
            db.close()

    def put(self, record, replace=False):
        validate_record(record)
        key = record["profile"]["id"]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM records WHERE id=?", (key,)).fetchone()
            if old:
                if json.loads(old[0])["profile"] == record["profile"]:
                    return "UNCHANGED"
                require(replace, "REMEASUREMENT_REQUIRES_REPLACE")
            require(old or db.execute("SELECT count(*) FROM records").fetchone()[0] < MAX_RECORDS, "INDEX_LIMIT_1000")
            db.execute("INSERT OR REPLACE INTO records VALUES (?,?)", (key, json.dumps(record, ensure_ascii=False, allow_nan=False)))
        return "REPLACED" if old else "INSERTED"

    def records(self):
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM records ORDER BY id LIMIT 1001").fetchall()
        require(len(rows) <= MAX_RECORDS, "INDEX_LIMIT_1000")
        result = [json.loads(r[0]) for r in rows]
        for r in result:
            validate_record(r)
        return result

    def delete(self, key=None):
        with self.connection() as db:
            if key is None:
                count = db.execute("DELETE FROM records").rowcount
            else:
                count = db.execute("DELETE FROM records WHERE id=?", (entry_id(key),)).rowcount
        with self.connection() as db:
            db.execute("VACUUM")
        return count

    def search(self, key, top=3):
        rows = self.records()
        require(len(rows) >= 3, "AT_LEAST_THREE_RECORDS_REQUIRED")
        return retrieval.search(key, [r["profile"] for r in rows], top=top, profile="acoustic")
