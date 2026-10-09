"""Private, offline researcher review; never a participant study or an approval."""
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from .audio import rights_ok
from .common import VERSION, digest, file_hash, identifier, require
from .design import eligible, screen


def provisional_trials(catalog, pairs):
    """List strict triples and a deterministic disjoint preview, not an optimum."""
    tracks = {t["id"]: t for t in catalog["tracks"]}
    options = []
    for source in sorted(tracks):
        buckets = {c: sorted(p["candidate"] for p in pairs if p["source"] == source and p.get("condition") == c)
                   for c in "ABCD"}
        for kind, first, second in (("primary", "A", "B"), ("control", "C", "D")):
            for a in buckets[first]:
                for b in buckets[second]:
                    if all(eligible(tracks[x], tracks[y]) for x, y in ((source, a), (source, b), (a, b))):
                        options.append({"kind": kind, "source": source, "first": a, "second": b,
                                        "status": "PROVISIONAL"})
    selected, used, artists, roles, kinds, sources = [], set(), Counter(), Counter(), Counter(), Counter()
    for trial in options:
        ids = [trial[k] for k in ("source", "first", "second")]
        hashes = {tracks[i][k] for i in ids for k in ("source_sha256", "clip_sha256")}
        creators = [tracks[i]["artist_id"] for i in ids]
        if (used & (set(ids) | hashes) or any(artists[a] >= 4 for a in creators)
                or kinds[trial["kind"]] >= {"primary": 6, "control": 2}[trial["kind"]]
                or sources[creators[0]] >= 2):
            continue
        next_roles = roles.copy()
        if trial["kind"] == "primary":
            next_roles[creators[1]] += 1
            next_roles[creators[2]] -= 1
        if any(abs(v) > 1 for v in next_roles.values()):
            continue
        selected.append(trial); used.update(set(ids) | hashes)
        artists.update(creators); roles = next_roles
        kinds[trial["kind"]] += 1; sources[creators[0]] += 1
        if len(selected) == 8:
            break
    return {"options": options, "disjoint_preview": selected,
            "selection_rule": "stable greedy; unique hashes/IDs, different creators within triples, max 4 recordings and 2 sources per creator, abs(A-B) <= 1, at most 6 A/B and 2 C/D; not a maximum packing",
            "status": "PROVISIONAL"}


def review_bundle(catalog, pool):
    require(catalog.get("schema") == VERSION and type(catalog.get("demo")) is bool, "Invalid catalog")
    labels = {t["id"]: t for t in pool["tracks"]}
    require(len(labels) == len(pool["tracks"]), "Duplicate metadata IDs")
    tracks = []
    for t in catalog["tracks"]:
        require(identifier(t["id"]) and t["id"] in labels, "Missing review label")
        rights_ok(t["rights"])
        require(file_hash(t["clip"]) == t["clip_sha256"], "Changed review clip")
        label = labels[t["id"]]
        # Deliberate allowlist: no original paths, rights ledger or download tokens.
        row = {k: t[k] for k in ("id", "artist_id", "source_sha256", "clip_sha256", "start", "seconds",
                                 "genre", "instrument", "raw_features", "features", "gain_db")}
        row.update({k: label.get(k) for k in ("title", "artist", "genre_source", "instrument_source")})
        row["tag_hints"] = {k: label.get(k, []) for k in ("genre", "instrument")}
        row["attribution"] = t["rights"]["attribution"]
        tracks.append(row)
    pairs = screen(catalog)["pairs"]
    trials = provisional_trials(catalog, pairs)
    return {"schema": "yanjaro.research-review.v1", "demo": catalog["demo"], "status": "PROVISIONAL",
            "catalog_sha256": digest(catalog), "tracks": tracks, "pairs": pairs, "trials": trials}


def export_review(catalog, pool, out, *, allow_real_audio=False):
    require(catalog.get("demo") is True or allow_real_audio, "Real audio review needs --allow-real-audio")
    out = Path(out).resolve()
    require(not out.exists(), "Review output directory must be new")
    require(not any((p / ".git").is_file() or (p / ".git" / "HEAD").is_file()
                    for p in (out, *out.parents)), "Keep review audio outside Git")
    bundle = review_bundle(catalog, pool)
    bundle["review_sha256"] = digest(bundle)
    total = sum(Path(t["clip"]).stat().st_size for t in catalog["tracks"])
    require(total <= 100 * 1024 * 1024, "Offline review audio exceeds 100 MiB")
    audio = {t["id"]: "data:audio/wav;base64," + base64.b64encode(Path(t["clip"]).read_bytes()).decode()
             for t in catalog["tracks"]}
    web = Path(__file__).parent / "web"
    css, js = (web / "review.css").read_text(), (web / "review.js").read_text()
    def csp_hash(value):
        return "'sha256-" + base64.b64encode(hashlib.sha256(value.encode()).digest()).decode() + "'"
    csp = f"default-src 'none'; media-src data:; style-src {csp_hash(css)}; script-src {csp_hash(js)}; base-uri 'none'; form-action 'none'"
    out.mkdir(parents=True, mode=0o700)
    for reviewer in ("reviewer-1", "reviewer-2"):
        data = json.dumps({**bundle, "reviewer": reviewer, "audio": audio}, ensure_ascii=False).replace("<", "\\u003c")
        html = (web / "review.html").read_text().replace("__CSP__", csp)
        html = html.replace("__CSS__", css).replace("__DATA__", data).replace("__JS__", js)
        fd = os.open(out / (reviewer + ".html"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
    return bundle
