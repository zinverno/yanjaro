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
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".tmp-", delete=False) as handle:
        tmp = Path(handle.name)
        os.chmod(tmp, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


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
    return data


def load_sessions(path: Path) -> dict:
    return read_json(path, empty_sessions())


def _valid_features(features: dict) -> bool:
    return (isinstance(features, dict) and all(
        name in features and isinstance(features[name], (float,int))
        and math.isfinite(features[name]) for name in FEATURE_NAMES))


def index_directory(root: Path, workspace: Path, max_files: int = 20,
                    max_seconds: int = 180, max_file_mb: int = 150) -> dict:
    """Index permitted local files only. No downloads, no audio data persisted."""
    from .audio import extract_file

    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir() or max_files < 1 or max_file_mb < 1:
        raise ValueError("Expected local directory and positive limits")
    library_file = Path(workspace) / "library.json"
    library = load_library(library_file)
    statuses = {"processed": 0, "skipped": 0, "errors": []}
    files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
                   and p.suffix.lower() in EXTENSIONS)
    for path in files:
        p = path.resolve(strict=True)
        stat = p.stat()
        if stat.st_size > max_file_mb * 1024 * 1024:
            statuses["skipped"] += 1
            continue
        track_id = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:16]
        old = library["tracks"].get(track_id)
        if old and old.get("size") == stat.st_size and old.get("mtime_ns") == stat.st_mtime_ns and old.get("max_seconds") == max_seconds:
            statuses["skipped"] += 1
            continue
        if statuses["processed"] >= max_files:
            break
        try:
            features = extract_file(p, max_seconds=max_seconds)
            if not _valid_features(features):
                raise ValueError("Incomplete features")
            library["tracks"][track_id] = {
                "path": str(p), "name": p.stem, "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "max_seconds": max_seconds,
                "features": features,
            }
            statuses["processed"] += 1
            # Retain progress if indexing is interrupted.
            write_json(library_file, library)
        except Exception as exc:
            statuses["errors"].append({"name": p.name, "error": type(exc).__name__})
    statuses["indexed_total"] = len(library["tracks"])
    statuses["audio_persisted"] = False
    return statuses


def new_session(sessions: dict, session_id: str, seeds: list[str], lib: dict) -> None:
    if not 1 <= len(session_id) <= 80 or not all(c.isalnum() or c in "_-." for c in session_id):
        raise ValueError("Use a 1–80-character session ID with letters/digits/_-.")
    seeds = list(dict.fromkeys(seeds))
    if not seeds or any(t not in lib["tracks"] for t in seeds):
        raise ValueError("Every seed must exist in the indexed library")
    if any(s["id"] == session_id for s in sessions["sessions"]):
        raise ValueError("Session already exists")
    sessions["sessions"].append({"id": session_id, "seed_ids": seeds,
                                 "ratings": {}, "created_at": datetime.now(timezone.utc).isoformat()})


def rate(sessions: dict, session_id: str, track_id: str, fit: bool, lib: dict) -> None:
    session = next((s for s in sessions["sessions"] if s["id"] == session_id), None)
    if session is None:
        raise ValueError("Session not found")
    if track_id not in lib["tracks"] or track_id in session["seed_ids"]:
        raise ValueError("Rate indexed non-seed tracks only")
    # Only explicit judgments; skipping a song is NOT labeled negative here.
    session["ratings"][track_id] = bool(fit)


def _feature_matrix(library: dict) -> tuple[list[str], np.ndarray]:
    ids = sorted(library["tracks"])
    if not ids:
        raise ValueError("Index some tracks first")
    for id in ids:
        if not _valid_features(library["tracks"][id]["features"]):
            raise ValueError("Incomplete or incompatible features in library")
    matrix = np.array([[library["tracks"][id]["features"][k] for k in FEATURE_NAMES] for id in ids], dtype=np.float64)
    return ids, matrix


def normalization(library: dict) -> tuple[list[float],list[float]]:
    _, matrix = _feature_matrix(library)
    mean = matrix.mean(axis=0)
    sd = matrix.std(axis=0)
    # Constant descriptors carry no information, avoid exploding tiny denominators.
    sd = np.where(sd < 1e-4, 1.0, sd)
    return mean.tolist(), sd.tolist()


def prior_weights() -> np.ndarray:
    w = np.array([PRIOR[k] for k in FEATURE_NAMES], dtype=np.float64)
    return w / np.sum(w)


def distance_vector(candidate: dict, seeds: list[dict], means, scales) -> np.ndarray:
    mean = np.asarray(means, dtype=np.float64)
    scale = np.asarray(scales, dtype=np.float64)
    c = np.array([candidate[k] for k in FEATURE_NAMES], dtype=np.float64)
    context = np.mean([[seed[k] for k in FEATURE_NAMES] for seed in seeds], axis=0)
    diff = np.clip(np.abs((c-context)/scale), 0.0, 4.0)
    # Tempo estimation has common half/double-time errors. Treat octave-equivalent
    # BPM as near, without confusing this with inferred 3/4 or 4/4 meter.
    ci = FEATURE_NAMES.index("bpm")
    t1, t2 = float(c[ci]), float(context[ci])
    if t1 > 0 and t2 > 0:
        ratio = math.log2(t1/t2)
        diff[ci] = min(4.0, min(abs(ratio),abs(ratio-1),abs(ratio+1))*4.0)
    elif t1 == t2 == 0:
        diff[ci] = 0.0  # Not evidence of same tempo: unavailable in both.
    else:
        diff[ci] = 1.5
    return diff


def _session_distances(lib: dict, session: dict, means, scales) -> dict[str,np.ndarray]:
    seeds = [lib["tracks"][t]["features"] for t in session["seed_ids"]]
    return {id: distance_vector(row["features"], seeds, means, scales)
            for id,row in lib["tracks"].items() if id not in session["seed_ids"]}


def pairs_for_sessions(lib: dict, sessions: list[dict], means, scales) -> np.ndarray:
    pairs=[]
    for s in sessions:
        d=_session_distances(lib,s,means,scales)
        positive = [id for id, fit in s["ratings"].items() if fit and id in d]
        negative = [id for id, fit in s["ratings"].items() if fit is False and id in d]
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
    eligible=[]
    for session in data["sessions"]:
        if not session.get("seed_ids") or any(t not in lib["tracks"] for t in session["seed_ids"]):
            continue
        ratings = {id:fit for id,fit in session.get("ratings",{}).items() if id in lib["tracks"] and id not in session["seed_ids"]}
        if True in ratings.values() and False in ratings.values():
            eligible.append({**session, "ratings":ratings})
    if len(eligible) < min_sessions:
        raise ValueError(f"Need {min_sessions} sessions with both positive and negative explicit votes; have {len(eligible)}")
    means, scales = normalization(lib)
    n_test = max(1, (len(eligible)+3)//4)
    train_s, test_s = eligible[:-n_test],eligible[-n_test:]
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
    if model:
        if model["version"] != SCHEMA_VERSION or model["feature_names"] != list(FEATURE_NAMES):
            raise ValueError("Model version/features mismatch")
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
        strongest=sorted(zip(FEATURE_NAMES,weights*d),key=lambda x:x[1])[:3]
        reasons=[name for name,_ in strongest]
        row=lib["tracks"][id]
        results.append({"id":id,"name":row["name"],"score":round(score,5),
                        "bpm_estimate":round(row["features"]["bpm"],1),"closest_features":reasons})
    return sorted(results,key=lambda r:(-r["score"],r["id"]))[:limit]
