"""Provisional pair screening, explicit manual review and frozen stimulus sets."""
import math
import random
from pathlib import Path
from .audio import rights_ok
from .common import VERSION, PROMPTS, digest, file_hash, identifier, number, require

POLICY = {
    "id": "screen-v1", "rhythm_near_max": .3, "rhythm_far_mean": .65,
    "rhythm_far_dimensions": 2, "tag_near_each": .5, "tag_far_each": .1,
    "scales": {"tempo_log2": .25, "onset_log2": 1., "regularity": .3,
               "onset_strength": .4, "energy_db": 6., "dynamic_range_db": 8.},
}


def tempo_distance(a, b):
    require(number(a, 20, 500) and number(b, 20, 500), "Unknown/invalid BPM")
    ratio = math.log2(max(a, b) / min(a, b))
    return min(abs(ratio + shift) for shift in (-1, 0, 1))


def tag_overlap(a, b):
    # Positive annotation overlap only. Empty data is unknown, never distance=1.
    if not a or not b:
        return None
    a, b = set(a), set(b)
    return len(a & b) / len(a | b)


def compare(a, b):
    x, y = a["features"], b["features"]
    genre = tag_overlap(a["genre"], b["genre"])
    instrument = tag_overlap(a["instrument"], b["instrument"])
    required = {"bpm": (20, 500), "onsets_per_second": (.01, 20),
                "onset_regularity": (0, 1), "onset_strength": (0, 1),
                "rms_db": (-100, 0), "dynamic_range_db": (0, 100)}
    if any(not number(f.get(k), *bounds) for f in (x, y) for k, bounds in required.items()):
        return {"condition": None, "reason": "unknown acoustic features"}
    if genre is None or instrument is None:
        return {"condition": None, "reason": "unknown tag coverage"}
    distances = [tempo_distance(x["bpm"], y["bpm"]) / .25,
                 abs(math.log2(x["onsets_per_second"] / y["onsets_per_second"])),
                 abs(x["onset_regularity"] - y["onset_regularity"]) / .3,
                 abs(x["onset_strength"] - y["onset_strength"]) / .4,
                 abs(x["rms_db"] - y["rms_db"]) / 6,
                 abs(x["dynamic_range_db"] - y["dynamic_range_db"]) / 8]
    rhythm = ("near" if max(distances) <= POLICY["rhythm_near_max"] else
              "far" if sum(min(d, 1) for d in distances) / len(distances) >= POLICY["rhythm_far_mean"]
              and sum(d >= 1 for d in distances) >= POLICY["rhythm_far_dimensions"] else "uncertain")
    tags = ("near" if min(genre, instrument) >= POLICY["tag_near_each"] else
            "far" if max(genre, instrument) <= POLICY["tag_far_each"] else "uncertain")
    condition = {("near", "far"): "A", ("far", "near"): "B",
                 ("near", "near"): "C", ("far", "far"): "D"}.get((rhythm, tags))
    return {"condition": condition, "rhythm": rhythm, "observed_tags": tags,
            "rhythm_distances": distances, "genre_overlap": genre, "instrument_overlap": instrument,
            "raw_tempo_log2": abs(math.log2(x["bpm"] / y["bpm"])),
            "reason": "Provisional proxies; listening review required"}


def eligible(a, b):
    return (a["id"] != b["id"] and a["artist_id"] != b["artist_id"]
            and a["source_sha256"] != b["source_sha256"] and a["clip_sha256"] != b["clip_sha256"]
            and abs(a["seconds"] - b["seconds"]) < .01)


def screen(catalog):
    require(catalog.get("schema") == VERSION and 3 <= len(catalog["tracks"]) <= 60, "Invalid catalog")
    pairs = []
    for source in catalog["tracks"]:
        for candidate in catalog["tracks"]:
            if eligible(source, candidate):
                result = compare(source, candidate)
                pairs.append({"source": source["id"], "candidate": candidate["id"], **result,
                              "review": {"approved": False, "rhythm_checked": False,
                                         "tags_checked": False, "tempo_alias_checked": False,
                                         "notes": ""}})
    return {"schema": VERSION, "catalog_sha256": digest(catalog), "policy": POLICY, "pairs": pairs}


def freeze(catalog, review, *, study_id, seed, phase):
    require(catalog.get("schema") == VERSION and type(catalog.get("demo")) is bool, "Invalid catalog schema")
    require(identifier(study_id) and type(seed) is int and 0 <= seed < 2**32, "Invalid study ID/seed")
    require(phase in ("demo", "pilot", "confirmatory"), "Invalid phase")
    require(catalog["demo"] == (phase == "demo"), "Demo cannot become real evidence")
    require(review.get("catalog_sha256") == digest(catalog) and review.get("policy") == POLICY,
            "Review does not match the catalog/policy")
    tracks = {t["id"]: t for t in catalog["tracks"]}
    require(len(tracks) == len(catalog["tracks"]), "Duplicate tracks")
    # The operator explicitly selects trials from the reviewed pool; no response-driven optimizer.
    trials = review.get("trials", [])
    require(2 <= len(trials) <= 32 and len({t["id"] for t in trials}) == len(trials), "Need 2..32 unique trials")
    pairs = {}
    for p in review["pairs"]:
        key = p["source"], p["candidate"]
        require(key not in pairs, "Duplicate pair reviews")
        pairs[key] = p
    used, sources = set(), set()
    for trial in trials:
        require(identifier(trial["id"]) and trial["kind"] in ("primary", "control"), "Invalid trial")
        require(set(trial) == {"id", "kind", "source", "first", "second"}, "Unexpected trial fields")
        ids = [trial[k] for k in ("source", "first", "second")]
        require(len(set(ids)) == 3 and all(t in tracks for t in ids), "Missing/repeated tracks")
        require(not used.intersection(ids), "A recording may occur only once per participant")
        require(trial["source"] not in sources, "Use each source once per participant")
        sources.add(trial["source"])
        used.update(ids)
        a, b, c = [tracks[t] for t in ids]
        require(all(eligible(x, y) for x, y in ((a, b), (a, c), (b, c))), "Duplicate/artist/duration confound")
        for candidate, expected in zip(ids[1:], ("A", "B") if trial["kind"] == "primary" else ("C", "D")):
            p = pairs.get((ids[0], candidate), {})
            require(p.get("condition") == expected and compare(a, tracks[candidate])["condition"] == expected,
                    "Pair does not meet its provisional condition")
            r = p.get("review", {})
            require(all(r.get(k) is True for k in ("approved", "rhythm_checked", "tags_checked", "tempo_alias_checked"))
                    and isinstance(r.get("notes"), str) and len(r["notes"].strip()) >= 12, "Manual pair review required")
    require(any(t["kind"] == "primary" for t in trials), "No primary contrast")
    selected = {t: tracks[t] for t in sorted(used)}
    for key in ("source_sha256", "clip_sha256"):
        require(len({t[key] for t in selected.values()}) == len(selected), "Repeated recording across trials")
    for t in selected.values():
        rights_ok(t["rights"])
        require(file_hash(t["clip"]) == t["clip_sha256"], "Clip changed since preparation")
    body = {"schema": VERSION, "study_id": study_id, "demo": catalog["demo"], "phase": phase,
            "seed": seed, "assignment_version": "schedule-v1", "policy": POLICY, "review_sha256": digest(review),
            "catalog_sha256": digest(catalog), "tracks": selected, "trials": trials}
    return {**body, "sha256": digest(body)}


def validate_study(study, *, audio=False):
    require(study.get("schema") == VERSION and study.get("sha256") == digest({k: v for k, v in study.items() if k != "sha256"}),
            "Study digest/schema mismatch")
    require(study.get("phase") in ("demo", "pilot", "confirmatory") and type(study.get("demo")) is bool
            and study["demo"] == (study["phase"] == "demo"), "Phase mismatch")
    require(2 <= len(study["trials"]) <= 32 and study["policy"] == POLICY
            and study.get("assignment_version") == "schedule-v1", "Invalid design")
    if audio:
        for track in study["tracks"].values():
            rights_ok(track["rights"])
            require(Path(track["clip"]).suffix == ".wav" and file_hash(track["clip"]) == track["clip_sha256"],
                    "Frozen audio missing or changed")


def schedule(study, slot, prompt):
    validate_study(study)
    require(type(slot) is int and 0 <= slot < 10000 and prompt in PROMPTS, "Invalid assignment")
    n = len(study["trials"])
    # Separate complete cycles per wording. In 2N slots: each task occurs twice in
    # each position, once with each orientation. Adjacent slots mirror each other.
    block, within = divmod(slot, 2 * n)
    rng = random.Random(f"{study['seed']}:{prompt}:{block}:schedule-v1")
    order = list(range(n))
    rng.shuffle(order)
    sides = [False] * n
    for kind in ("primary", "control"):
        indices = [i for i, task in enumerate(study["trials"]) if task["kind"] == kind]
        rng.shuffle(indices)
        for j, i in enumerate(indices):
            sides[i] = j % 2 == 0
    shift = within // 2
    order = order[shift:] + order[:shift]
    return [{**study["trials"][i], "first_left": sides[i] != bool(within % 2)} for i in order]


def public_bundle(study, slot, prompt):
    def url(tid):
        return "/audio/" + digest({"study": study["sha256"], "track": tid})[:32]
    trials = []
    for t in schedule(study, slot, prompt):
        left, right = (t["first"], t["second"]) if t["first_left"] else (t["second"], t["first"])
        trials.append({"id": t["id"], "source": url(t["source"]), "left": url(left), "right": url(right)})
    return {"schema": VERSION, "study_id": study["study_id"], "study_sha256": study["sha256"],
            "demo": study["demo"], "phase": study["phase"], "slot": slot,
            "prompt_id": prompt, "prompt": PROMPTS[prompt], "trials": trials}
