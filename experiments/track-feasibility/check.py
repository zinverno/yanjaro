#!/usr/bin/env python3
"""Offline audit replay and candidate search. Never reads or downloads audio."""

import argparse
import csv
import hashlib
import json
import platform
import time
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLE_SHA256 = "7499bd512e07694e841054f70b7cb58d6bc9d6c1c43489884b8ff656ca3a29d5"
JAMENDO_COMMIT = "cafd8e20c265ed84f1e61f1c875327971f43a62f"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample(path=ROOT / "sample.json"):
    if sha256(path) != SAMPLE_SHA256:
        raise ValueError("Frozen sample changed; create a new study instead")
    rows = read_json(path)["tracks"]
    ids = [r["yandex_track_id"] for r in rows]
    if len(ids) != 30 or len(set(ids)) != 30 or not all(i.isdecimal() for i in ids):
        raise ValueError("Expected 30 distinct decimal Yandex IDs")
    return rows


def normalized(value):
    # shortcut: no aliases/transliteration; this is candidate discovery, not absence proof.
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def scan_jamendo(path, rows):
    started = time.perf_counter()
    matches = {r["yandex_track_id"]: {"artist_title_candidates": [], "title_only_count": 0} for r in rows}
    wanted = {}
    for row in rows:
        wanted.setdefault(normalized(row["discovery_claim"]["title"]), []).append(row)
    total = 0
    rejected = []
    seen = set()
    with path.open(encoding="utf-8", newline="") as handle:
        # Names contain literal quotes; CSV quote handling would swallow later rows.
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        required = {"TRACK_ID", "ARTIST_NAME", "TRACK_NAME", "ALBUM_NAME", "URL"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Not a Jamendo raw.meta.tsv: required columns missing")
        for line, entry in enumerate(reader, 2):
            if None in entry or any(entry.get(key) is None for key in required):
                rejected.append({"line": line, "track_id": entry.get("TRACK_ID"), "reason": "column_count"})
                continue
            if not entry["TRACK_ID"].startswith("track_") or entry["TRACK_ID"] in seen:
                raise ValueError("Invalid or duplicate Jamendo track ID")
            seen.add(entry["TRACK_ID"])
            total += 1
            for row in wanted.get(normalized(entry["TRACK_NAME"]), []):
                result = matches[row["yandex_track_id"]]
                result["title_only_count"] += 1
                if normalized(row["discovery_claim"]["artist"]) == normalized(entry["ARTIST_NAME"]):
                    result["artist_title_candidates"].append({
                        "namespace": "jamendo_track", "id": entry["TRACK_ID"],
                        "artist": entry["ARTIST_NAME"], "title": entry["TRACK_NAME"],
                        "release": entry["ALBUM_NAME"], "source_url": entry["URL"],
                        "identity": "CANDIDATE_ONLY",
                    })
    if not total:
        raise ValueError("Empty dataset is not a completed search")
    return {
        "source_url": f"https://github.com/MTG/mtg-jamendo-dataset/blob/{JAMENDO_COMMIT}/data/raw.meta.tsv",
        "sha256": sha256(path), "bytes": path.stat().st_size, "rows_scanned": total,
        "rejected_rows": rejected,
        "algorithm": "NFKC + casefold + whitespace; exact artist and title; no identity inference",
        "seconds": round(time.perf_counter() - started, 6), "python": platform.python_version(),
        "scope": "valid rows of supplied metadata table; rejected rows and aliases remain unchecked; not entire Jamendo catalog",
        "matches": matches,
    }


def identity_checks(row):
    fields = row["yandex_metadata"]
    candidates = row["external_candidates"]
    return {
        "yandex_isrc_available": fields["isrc"]["value"] is not None,
        "yandex_duration_available": fields["duration_ms"]["value"] is not None,
        "recording_crosswalk_verified": any(c["identity"] == "EXACT_RECORDING" for c in candidates),
        "release_crosswalk_supported": any(c["identity"] == "RELEASE_LINK_SUPPORTED" for c in candidates),
        "reason": "Artist/title, release links, external ISRCs and numeric-ID equality cannot establish the same master alone.",
    }


def replay(rows, evidence, jamendo):
    if evidence["sample_sha256"] != SAMPLE_SHA256:
        raise ValueError("Evidence refers to another sample")
    observations = evidence["tracks"]
    expected = [r["yandex_track_id"] for r in rows]
    if [r["yandex_track_id"] for r in observations] != expected:
        raise ValueError("Evidence missing, reordered, or substituted")
    if set(jamendo["matches"]) != set(expected) or jamendo["rows_scanned"] <= 0:
        raise ValueError("Incomplete dataset receipt")
    output = []
    for frozen, observation in zip(rows, observations):
        for field in ("artist", "title", "duration_ms", "version", "release", "isrc", "album_id"):
            item = observation["yandex_metadata"][field]
            if item["value"] is not None and (not item["source_url"] or not item["basis"]):
                raise ValueError("Metadata value lacks provenance")
        if observation["acoustic_vector"] is not None:
            raise ValueError("This frozen metadata-only study has no verified vector receipt")
        # No positive acoustic result is supported by this study's observations.
        for candidate in observation["external_candidates"]:
            if candidate["identity"] not in ("CANDIDATE_ONLY", "RELEASE_LINK_SUPPORTED", "REJECTED_VARIANT"):
                raise ValueError("Unsupported promotion to exact recording")
            if not candidate["source_url"].startswith("https://"):
                raise ValueError("Candidate lacks a public evidence URL")
            if candidate["namespace"] not in ("musicbrainz_release", "musicbrainz_recording", "musicbrainz_artist", "musicbrainz_work", "wikidata_item"):
                raise ValueError("Unreviewed ID namespace (Yambda IDs are not Yandex IDs)")
            if candidate["identity"] == "RELEASE_LINK_SUPPORTED" and candidate.get("yandex_album_id") != frozen["yandex_album_id"]:
                raise ValueError("Release crosswalk contradicts the frozen album ID")
        primary = observation["yandex_metadata"]["artist"]["basis"] == "yandex_public_page"
        status = "METADATA_ONLY" if primary else "BLOCKED"
        output.append({
            **frozen, **observation, "status": status,
            "identity_checks": identity_checks(observation),
            "jamendo": jamendo["matches"][frozen["yandex_track_id"]],
            "exact_recording_match": False, "permitted_acoustic_source_verified": False,
        })
    counts = Counter(r["status"] for r in output)
    return {
        "schema": "yanjaro.track-feasibility.results.v1",
        "sample_sha256": SAMPLE_SHA256, "observed_date": evidence["observed_date"],
        "summary": {
            "sample_size": len(output), "public_id_attestations": len(output),
            "primary_yandex_partial_metadata": counts["METADATA_ONLY"],
            "full_yandex_metadata": sum(all(r["yandex_metadata"][k]["value"] is not None for k in ("artist", "title", "duration_ms", "version", "release")) for r in output),
            "canonical_region_pages": sum(r["canonical_probe"]["outcome"] == "REGION_UNAVAILABLE" for r in output),
            "canonical_tool_errors": sum(r["canonical_probe"]["outcome"] == "TOOL_ERROR" for r in output),
            "external_candidate_rows": sum(any(c["identity"] != "REJECTED_VARIANT" for c in r["external_candidates"]) for r in output),
            "release_crosswalk_rows": sum(r["identity_checks"]["release_crosswalk_supported"] for r in output),
            "exact_recording_matches": sum(r["exact_recording_match"] for r in output),
            "permitted_acoustic_sources_verified": sum(r["permitted_acoustic_source_verified"] for r in output),
            "acoustic_vectors": sum(r["acoustic_vector"] is not None for r in output),
            "without_end_to_end_solution": sum(not r["permitted_acoustic_source_verified"] for r in output),
            "status_counts": dict(counts),
        }, "tracks": output,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jamendo-metadata", type=Path, help="Scan an already downloaded metadata TSV; no network")
    args = parser.parse_args()
    rows = sample()
    if args.jamendo_metadata:
        result = scan_jamendo(args.jamendo_metadata, rows)
    else:
        result = replay(rows, read_json(ROOT / "observations.json"), read_json(ROOT / "jamendo-scan.json"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
