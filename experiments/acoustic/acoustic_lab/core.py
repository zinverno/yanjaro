"""Local acoustic baseline + a genuinely trained, constrained pairwise ranker.

No recommendations or audio are requested from Yandex servers. There is no trained
model until explicit within-session positive AND negative labels exist.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

import numpy as np

from . import FEATURE_NAMES, PRIOR, SCHEMA_VERSION

EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


def write_json(path: Path, value: dict) -> None:
    """Owner-only atomic local state file. Never write under version control by default."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".tmp-", delete=False) as handle:
            tmp = Path(handle.name)
            os.chmod(tmp, 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def read_json(path: Path, default: dict) -> dict:
    p = Path(path)
    if not p.exists():
        return default
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("version") != SCHEMA_VERSION:
        raise ValueError("Unsupported local data version; do not silently mix feature schemas")
    return obj


def empty_library() -> dict:
    return {"version": SCHEMA_VERSION, "feature_names": list(FEATURE_NAMES), "tracks": {}}


def empty_sessions() -> dict:
    return {"version": SCHEMA_VERSION, "sessions": []}


def load_library(path: Path) -> dict:
    data = read_json(path, empty_library())
    if data.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("Acoustic features changed; reindex separately")
    tracks = data.get("tracks")
    if not isinstance(tracks, dict) or any(
        not isinstance(id, str) or not id or not isinstance(row, dict)
        or not isinstance(row.get("name"), str) or not _valid_features(row.get("features"))
        for id, row in tracks.items()
    ):
        raise ValueError("Invalid library tracks or acoustic features")
    return data


def load_sessions(path: Path) -> dict:
    data = read_json(path, empty_sessions())
    validate_sessions(data)
    return data


def _timestamp(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Session timestamps must be ISO dates with timezone")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Session timestamps require a timezone")
    return stamp


def validate_sessions(data: dict) -> None:
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION or not isinstance(data.get("sessions"), list):
        raise ValueError("Invalid session schema")
    seen = set()
    for s in data["sessions"]:
        if not isinstance(s, dict) or not _valid_session_id(s.get("id")) or s["id"] in seen:
            raise ValueError("Invalid or duplicate session ID")
        seen.add(s["id"])
        seeds, ratings = s.get("seed_ids"), s.get("ratings")
        if (not isinstance(seeds, list) or not seeds or any(not isinstance(t, str) or not t for t in seeds)
                or len(set(seeds)) != len(seeds) or not isinstance(ratings, dict)
                or any(not isinstance(t, str) or not t or type(fit) is not bool or t in seeds for t, fit in ratings.items())):
            raise ValueError("Invalid session seeds or explicit ratings")
        for field, ids in (("seed_features", seeds), ("rating_features", ratings)):
            snapshots = s.get(field)
            if (not isinstance(snapshots, dict) or set(snapshots) != set(ids)
                    or not all(_valid_features(f) for f in snapshots.values())):
                raise ValueError("Invalid session feature snapshots; create a new session")
        if _timestamp(s.get("updated_at")) < _timestamp(s.get("created_at")):
            raise ValueError("Session feedback cannot predate its context")


def _valid_session_id(value) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 80
            and all(c.isalnum() or c in "_-." for c in value))


def _valid_features(features: dict) -> bool:
    return (isinstance(features, dict) and all(
        name in features and type(features[name]) in (float,int)
        and math.isfinite(features[name]) for name in FEATURE_NAMES))


def index_directory(root: Path, workspace: Path, max_files: int = 20,
                    max_seconds: int = 180, max_file_mb: int = 150) -> dict:
    """Index permitted local files only. No downloads, no audio data persisted."""
    from .audio import extract_file

    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir() or max_files < 1 or max_file_mb < 1:
        raise ValueError("Expected local directory and positive limits")
    if not 10 <= max_seconds <= 300:
        raise ValueError("max_seconds must be between 10 and 300")
    library_file = Path(workspace) / "library.json"
    library = load_library(library_file)
    statuses = {"processed": 0, "attempted": 0, "skipped": 0, "errors": []}
    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
                   and p.suffix.lower() in EXTENSIONS)
    for path in files:
        if statuses["attempted"] >= max_files:
            break
        try:
            p = path.resolve(strict=True)
            stat = p.stat()
        except OSError as exc:
            statuses["attempted"] += 1
            statuses["errors"].append({"name": path.name, "error": type(exc).__name__})
            continue
        if stat.st_size > max_file_mb * 1024 * 1024:
            statuses["skipped"] += 1
            continue
        track_id = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:16]
        old = library["tracks"].get(track_id)
        if old and old.get("size") == stat.st_size and old.get("mtime_ns") == stat.st_mtime_ns and old.get("max_seconds") == max_seconds:
            statuses["skipped"] += 1
            continue
        statuses["attempted"] += 1
        try:
            features = extract_file(p, max_seconds=max_seconds)
            if not _valid_features(features):
                raise ValueError("Incomplete features")
            library["tracks"][track_id] = {
                "path": str(p), "name": p.stem, "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "max_seconds": max_seconds,
                "features": features,
            }
        except Exception as exc:
            statuses["errors"].append({"name": p.name, "error": type(exc).__name__})
            continue
        # Storage failures abort the command; they are not audio decode failures.
        write_json(library_file, library)
        statuses["processed"] += 1
    statuses["indexed_total"] = len(library["tracks"])
    statuses["audio_persisted"] = False
    return statuses


def new_session(sessions: dict, session_id: str, seeds: list[str], lib: dict) -> None:
    if not _valid_session_id(session_id):
        raise ValueError("Use a 1–80-character session ID with letters/digits/_-.")
    seeds = list(dict.fromkeys(seeds))
    if not seeds or any(t not in lib["tracks"] for t in seeds):
        raise ValueError("Every seed must exist in the indexed library")
    if any(s["id"] == session_id for s in sessions["sessions"]):
        raise ValueError("Session already exists")
    snapshots = {t: dict(lib["tracks"][t]["features"]) for t in seeds}
    if not all(_valid_features(f) for f in snapshots.values()):
        raise ValueError("Invalid seed features")
    now = datetime.now(timezone.utc).isoformat()
    sessions["sessions"].append({"id": session_id, "seed_ids": seeds,
                                 "seed_features": snapshots, "rating_features": {},
                                 "ratings": {}, "created_at": now, "updated_at": now})


def rate(sessions: dict, session_id: str, track_id: str, fit: bool, lib: dict) -> None:
    if type(fit) is not bool:
        raise ValueError("An explicit boolean vote is required")
    session = next((s for s in sessions["sessions"] if s["id"] == session_id), None)
    if session is None:
        raise ValueError("Session not found")
    if track_id not in lib["tracks"] or track_id in session["seed_ids"]:
        raise ValueError("Rate indexed non-seed tracks only")
    features = lib["tracks"][track_id]["features"]
    if not _valid_features(features):
        raise ValueError("Invalid candidate features")
    if track_id in session["ratings"] and session["ratings"][track_id] == fit:
        return  # Repeating feedback is idempotent, including its time and snapshot.
    # Only explicit judgments; skipping a song is NOT labeled negative here.
    session["ratings"][track_id] = fit
    session["rating_features"].setdefault(track_id, dict(features))
    session["updated_at"] = datetime.now(timezone.utc).isoformat()


def _feature_matrix(library: dict) -> tuple[list[str], np.ndarray]:
    ids = sorted(library["tracks"])
    if not ids:
        raise ValueError("Index some tracks first")
    for id in ids:
        if not _valid_features(library["tracks"][id]["features"]):
            raise ValueError("Incomplete or incompatible features in library")
    matrix = np.array([[library["tracks"][id]["features"][k] for k in FEATURE_NAMES] for id in ids], dtype=np.float64)
    return ids, matrix


def normalization(library: dict, sessions: list[dict] | None = None) -> tuple[list[float],list[float]]:
    if sessions is None:
        _, matrix = _feature_matrix(library)
    else:
        matrix = np.array([[f[k] for k in FEATURE_NAMES] for s in sessions
                           for field in ("seed_features", "rating_features")
                           for _, f in sorted(s[field].items())], dtype=np.float64)
    mean = matrix.mean(axis=0)
    sd = matrix.std(axis=0)
    # Constant descriptors carry no information, avoid exploding tiny denominators.
    sd = np.where(sd < 1e-4, 1.0, sd)
    return mean.tolist(), sd.tolist()


def prior_weights() -> np.ndarray:
    w = np.array([PRIOR[k] for k in FEATURE_NAMES], dtype=np.float64)
    return w / np.sum(w)


def distance_vector(candidate: dict, seeds: list[dict], means, scales) -> np.ndarray:
    scale = np.asarray(scales, dtype=np.float64)
    c = np.array([candidate[k] for k in FEATURE_NAMES], dtype=np.float64)
    context = np.mean([[seed[k] for k in FEATURE_NAMES] for seed in seeds], axis=0)
    diff = np.clip(np.abs((c-context)/scale), 0.0, 4.0)
    # Tempo estimation has common half/double-time errors. Treat octave-equivalent
    # BPM as near, without confusing this with inferred 3/4 or 4/4 meter.
    ci = FEATURE_NAMES.index("bpm")
    t1 = float(c[ci])
    tempos = [float(s["bpm"]) for s in seeds if s["bpm"] > 0]
    if t1 > 0 and tempos:
        # Average octave-aware distances, not raw BPM (70 + 140 is not 105 BPM).
        ratios = [math.log2(t1 / t2) for t2 in tempos]
        diff[ci] = float(np.mean([min(4.0, min(abs(r), abs(r-1), abs(r+1))*4.0) for r in ratios]))
    else:
        diff[ci] = 1.5  # Unknown tempo is not evidence of an exact match.
    return diff


def _session_distances(lib: dict, session: dict, means, scales) -> dict[str,np.ndarray]:
    seeds = list(session["seed_features"].values())
    return {id: distance_vector(row["features"], seeds, means, scales)
            for id,row in lib["tracks"].items() if id not in session["seed_ids"]}


def pairs_for_sessions(lib: dict, sessions: list[dict], means, scales) -> np.ndarray:
    pairs=[]
    for s in sessions:
        seeds = list(s["seed_features"].values())
        d = {id: distance_vector(f, seeds, means, scales) for id, f in s["rating_features"].items()}
        positive = sorted(id for id, fit in s["ratings"].items() if fit)
        negative = sorted(id for id, fit in s["ratings"].items() if fit is False)
        for yes in positive:
            for no in negative:
                pairs.append(d[no]-d[yes])
    return np.array(pairs,dtype=np.float64).reshape(-1,len(FEATURE_NAMES))


def pair_accuracy(pairs: np.ndarray, weights: np.ndarray) -> float | None:
    if not len(pairs):
        return None
    margin=pairs @ weights
    return round(float(np.mean((margin>1e-10)+.5*(np.abs(margin)<=1e-10))),4)


def train_ranker(lib: dict, data: dict, min_sessions: int = 6) -> dict:
    """Learn *which acoustic distances matter* from explicit, session-local votes.

    Non-negative pairwise logistic regression shrunk toward rhythm-first prior.
    The last 25% of eligible sessions are held out chronologically.
    """
    validate_sessions(data)
    if min_sessions < 6:
        raise ValueError("At least 6 sessions are required")
    eligible=[]
    for session in data["sessions"]:
        ratings = session["ratings"]
        if True in ratings.values() and False in ratings.values():
            eligible.append(session)
    if len(eligible) < min_sessions:
        raise ValueError(f"Need {min_sessions} sessions with both positive and negative explicit votes; have {len(eligible)}")
    eligible.sort(key=lambda s: (_timestamp(s["created_at"]), s["id"]))
    n_test = max(1, (len(eligible)+3)//4)
    train_s, test_s = eligible[:-n_test],eligible[-n_test:]
    if max(_timestamp(s["updated_at"]) for s in train_s) >= min(_timestamp(s["created_at"]) for s in test_s):
        raise ValueError("Training feedback overlaps holdout time; collect sequential, independent sessions")
    means, scales = normalization(lib, train_s)
    train_pairs=pairs_for_sessions(lib,train_s,means,scales)
    test_pairs=pairs_for_sessions(lib,test_s,means,scales)
    if len(train_pairs)<4 or len(test_pairs)<1:
        raise ValueError("Not enough positive-vs-negative pairs in train/holdout sessions")
    prior=prior_weights()
    w=prior.copy()
    # Gradient descent on pairwise logistic loss with L2 shrinkage and w >= 0.
    # Constrained to avoid claiming that a more-different song is a better match.
    for _ in range(900):
        margins=np.clip(3 * (train_pairs @ w), -30, 30)
        gradient=-(3 * train_pairs * (1 / (1 + np.exp(margins)))[:,None]).mean(axis=0)
        gradient+=1.5*(w-prior)
        w=np.clip(w-.035*gradient, 0, np.maximum(prior*4, .08))
    return {
        "version": SCHEMA_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "model_type":"nonnegative_pairwise_logistic_distance_reranker",
        "means": means,
        "scales": scales,
        "weights": [round(float(x),9) for x in w],
        "training": {
            "train_sessions":len(train_s), "holdout_sessions":len(test_s),
            "train_session_ids": [s["id"] for s in train_s],
            "holdout_session_ids": [s["id"] for s in test_s],
            "normalization": "training session feature snapshots only",
            "train_pairs":len(train_pairs),"holdout_pairs":len(test_pairs),
            "baseline_holdout_pair_accuracy":pair_accuracy(test_pairs,prior),
            "learned_holdout_pair_accuracy":pair_accuracy(test_pairs,w),
            "note":"Exploratory offline result, not an unbiased proof of improvement. Sessions held out chronologically."
        },
        "saved_at": datetime.now(timezone.utc).isoformat()
    }


def recommend(lib: dict, session: dict, model: dict | None=None, limit: int = 10) -> list[dict]:
    if not 1<=limit<=100:
        raise ValueError("limit must be 1..100")
    if model is not None:
        if not isinstance(model, dict) or model.get("version") != SCHEMA_VERSION or model.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("Model version/features mismatch")
        for key in ("means", "scales", "weights"):
            vector = model.get(key)
            if (not isinstance(vector, list) or len(vector) != len(FEATURE_NAMES)
                    or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)):
                raise ValueError("Invalid model vectors")
        if any(s <= 0 for s in model["scales"]) or any(w < 0 for w in model["weights"]):
            raise ValueError("Model scales must be positive and weights nonnegative")
        means,scales = model["means"],model["scales"]
        weights=np.asarray(model["weights"],dtype=float)
    else:
        means,scales=normalization(lib)
        weights=prior_weights()
    dist=_session_distances(lib,session,means,scales)
    exclusions=set(session["seed_ids"]) | set(session.get("ratings",{}))
    results=[]
    for id,d in dist.items():
        if id in exclusions:
            continue
        score=-float(weights@d)
        # An actual readable explanation, based on weighted distances.
        has_tempo = (lib["tracks"][id]["features"]["bpm"] > 0
                     and any(f["bpm"] > 0 for f in session["seed_features"].values()))
        contributions = [(name, weight*delta) for name,weight,delta in zip(FEATURE_NAMES,weights,d)
                         if weight > 0 and (name != "bpm" or has_tempo)]
        strongest=sorted(contributions,key=lambda x:x[1])[:3]
        reasons=[name for name,_ in strongest]
        row=lib["tracks"][id]
        results.append({"id":id,"name":row["name"],"score":round(score,5),
                        "bpm_estimate":round(row["features"]["bpm"],1),"closest_features":reasons})
    return sorted(results,key=lambda r:(-r["score"],r["id"]))[:limit]
