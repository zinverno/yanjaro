"""Local, hash-bound research inputs; no network or implicit rights grants."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEMA = "yanjaro.acoustic-similarity.v0.1"
ASPECTS = ("rhythm", "timbre", "energy")
CASES = ("same_genre_different_rhythm", "different_genre_similar_rhythm",
         "same_tempo_different_instrumentation")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def is_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def artist_clusters(tracks):
    """Overlapping collaborations belong to one bootstrap/split count group."""
    parent = {a: a for t in tracks.values() for a in t["artist_ids"]}
    def root(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for t in tracks.values():
        first = t["artist_ids"][0]
        for a in t["artist_ids"][1:]:
            parent[root(a)] = root(first)
    return {tid: root(t["artist_ids"][0]) for tid, t in tracks.items()}


def read_json(path):
    def reject(value):
        raise ValueError("Nonfinite JSON: " + value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def write_new(path, value):
    """Publish complete owner-only JSON, refusing overwrite, even in a race."""
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".similarity-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path)
    finally:
        os.unlink(tmp)


def validate_manifest(manifest, *, purpose="analysis", verify_files=False):
    require(manifest.get("schema") == SCHEMA, "Unsupported dataset schema")
    require(manifest.get("kind") in ("real", "synthetic-test-only"), "Dataset kind required")
    require(bool(manifest.get("dataset_id")), "Dataset version/id required")
    rows = manifest.get("tracks", [])
    require(isinstance(rows, list) and 1 <= len(rows) <= 50000, "Need 1..50000 explicit records")
    seen_ids, seen_hashes, groups = set(), set(), {}
    for t in rows:
        require(isinstance(t.get("id"), str) and t["id"] and t["id"] not in seen_ids,
                "Missing/duplicate track ID")
        seen_ids.add(t["id"])
        require(is_hash(t.get("sha256")) and t["sha256"] not in seen_hashes,
                "Missing/duplicate audio hash")
        seen_hashes.add(t["sha256"])
        require(t.get("split") in ("train", "validation", "test", "diagnostic"), "Invalid split")
        require(isinstance(t.get("artist_ids"), list) and t["artist_ids"] and
                all(isinstance(a, str) and a.strip() for a in t["artist_ids"]), "Artist identities required")
        require(isinstance(t.get("recording_group"), str) and t["recording_group"], "Recording group required")
        for group in [*("artist:" + a for a in t["artist_ids"]), "recording:" + t["recording_group"]]:
            require(group not in groups or groups[group] == t["split"], "Artist/recording split leakage")
            groups[group] = t["split"]
        require(type(t.get("start")) in (int, float) and 0 <= t["start"] <= 36000 and
                type(t.get("seconds")) in (int, float) and 10 <= t["seconds"] <= 90,
                "Expected a fixed 10..90 second window")
        r = t.get("rights", {})
        for key in ("reviewed", "acquisition", "analysis"):
            require(r.get(key) is True, "Missing rights: " + key)
        for key in ("license", "source_url", "attribution", "verified_on", "scope"):
            require(isinstance(r.get(key), str) and r[key].strip(), "Missing rights evidence: " + key)
        require(is_hash(r.get("evidence_sha256")) and bool(r.get("evidence_path")), "Evidence snapshot required")
        if purpose in ("training", "remote"):
            require(r.get(purpose) is True, "Missing explicit rights/scope: " + purpose)
    # All declarations are checked before any recording is read.
    if verify_files:
        for t in rows:
            path = Path(t["path"])
            require(path.is_file() and path.stat().st_size <= 512 * 1024**2,
                    "Expected a local audio file <=512 MiB")
            require(file_hash(t["rights"]["evidence_path"]) == t["rights"]["evidence_sha256"],
                    "Rights evidence changed")
            require(file_hash(path) == t["sha256"], "Audio hash changed")
    return {t["id"]: t for t in rows}


def validate_labels(labels, manifest):
    tracks = validate_manifest(manifest)
    require(labels.get("schema") == SCHEMA and labels.get("purpose") == "acoustic_similarity",
            "Only acoustic similarity labels are accepted")
    require(labels.get("dataset_sha256") == digest(manifest), "Labels belong to another dataset")
    require(labels.get("kind") == manifest["kind"], "Label/data kind mismatch")
    rows = labels.get("triplets", [])
    require(isinstance(rows, list), "Triplet list required")
    seen = set()
    for t in rows:
        require(t.get("aspect") in ASPECTS, "Unknown acoustic aspect")
        ids = [t.get(k) for k in ("anchor", "positive", "negative")]
        require(len(set(ids)) == 3 and all(i in tracks for i in ids), "Invalid triplet recordings")
        require(len({tracks[i]["split"] for i in ids}) == 1 and
                tracks[ids[0]]["split"] != "diagnostic", "Triplet crosses split")
        key = (t["aspect"], ids[0], *sorted(ids[1:]))
        require(key not in seen, "Duplicate or contradictory triplet")
        seen.add(key)
        expected = "human_acoustic_comparison" if manifest["kind"] == "real" else "synthetic-test-only"
        require(t.get("source") == expected and t.get("agreement") == "agreed",
                "Unreviewed/preference/genre-derived labels rejected")
        require(isinstance(t.get("reviewer_ids"), list) and len(set(t["reviewer_ids"])) >= 2 and
                all(isinstance(x, str) and x for x in t["reviewer_ids"]), "Two independent review IDs required")
        require(bool(t.get("evidence")), "Label provenance required")
        require(isinstance(t.get("cases"), list) and set(t["cases"]) <= set(CASES), "Invalid evaluation cases")
    return rows
