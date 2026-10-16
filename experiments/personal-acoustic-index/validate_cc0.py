"""Opt-in, bounded replay of the existing ten CC0 files; private results, no audio copies."""
import argparse
import json
import os
from pathlib import Path
import resource
import sys
import time

from runtime import configure
configure()
import core
from acoustic_similarity.data import file_hash, validate_manifest


def run(manifest_path, index_dir):
    manifest = json.loads(Path(manifest_path).read_text())
    tracks = validate_manifest(manifest, verify_files=True)
    core.require(len(tracks) == 10 and all(t["rights"]["license"] == "CC0-1.0" for t in tracks.values()),
                 "EXPECTED_EXISTING_TEN_CC0_FILES")
    index = core.Index(index_dir)
    core.require(not index.records(), "CC0_TEST_REQUIRES_EMPTY_INDEX")
    historical = json.loads((Path(__file__).resolve().parents[1] /
                             "acoustic-similarity/validation/acoustic-retrieval-v1/index.json").read_text())
    old = {r["id"]: r for r in historical["tracks"]}
    receipts = []
    started = time.monotonic()
    for key, track in tracks.items():
        core.require(old[key]["audio_sha256"] == track["sha256"], "CC0_REFERENCE_IDENTITY_MISMATCH")
        pcm, sr = core.read_file(track["path"], track["start"], track["seconds"])
        try:
            row = core.extract(pcm, sr, "cc0-" + key, core.identity(), "file")
        except core.Rejected as exc:
            receipts.append(dict(id=key, status="REJECTED", reason=str(exc)))
            continue
        errors = {}
        for block, value in row["profile"]["blocks"].items():
            reference = old[key]["blocks"][block]
            core.require((value is None) == (reference is None), "CC0_MISSINGNESS_DRIFT")
            if value is not None:
                errors[block] = float(core.np.max(core.np.abs(core.np.asarray(value) - reference)))
            else:
                errors[block] = None
        maximum = max(v for v in errors.values() if v is not None)
        core.require(maximum <= 1e-6, "FROZEN_COMPONENT_DRIFT")
        index.put(row)
        repeat_pcm, rate = core.read_file(track["path"], track["start"], track["seconds"])
        repeat = core.extract(repeat_pcm, rate, "cc0-" + key, core.identity(), "file")
        core.require(repeat["profile"] == row["profile"] and index.put(repeat) == "UNCHANGED", "REPEAT_DRIFT")
        core.require(file_hash(track["path"]) == track["sha256"] and (pcm == 0).all() and (repeat_pcm == 0).all(),
                     "SOURCE_OR_BUFFER_INTEGRITY_FAILED")
        receipts.append(dict(id=key, status="INDEXED", dimension=705, frozen_block_max_error=maximum,
                             frozen_component_errors=errors, signal_quality=row["quality"],
                             legacy_would_reject=row["quality"]["peak"] > 1.001 or row["quality"]["clipped_fraction"] > .001,
                             repeat_equal=True, buffers_zeroed=True, source_unchanged=True))
        print(json.dumps(receipts[-1]), flush=True)
    rows = index.records()
    core.require(len(rows) >= 3, "INSUFFICIENT_CC0_RECORDS_FOR_SEARCH")
    rankings = {r["profile"]["id"]: index.search(r["profile"]["id"], 3) for r in rows}
    summary = dict(schema="yanjaro.personal-cc0-check.v2", base_head=core.BASE_HEAD, quality_policy=core.QUALITY_POLICY,
                   submitted=len(tracks), indexed=len(rows), rejected=len(tracks) - len(rows),
                   dimensions=705, query_count=len(rankings),
                   source_audio_copied=False, audio_saved=False, vectors_public=False,
                   max_frozen_block_error=max(r.get("frozen_block_max_error", 0) for r in receipts),
                   max_frozen_component_errors={k: max(r["frozen_component_errors"][k] or 0 for r in receipts
                       if r["status"] == "INDEXED") for k in core.retrieval.NAMES},
                   accepted_with_caution=sum(r.get("signal_quality", {}).get("status") == "ACCEPTED_WITH_CAUTION"
                                             for r in receipts),
                   repeat_equal=all(r.get("repeat_equal", False) for r in receipts if r["status"] == "INDEXED"),
                   elapsed_seconds=round(time.monotonic() - started, 3),
                   peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   affinity_cpus=len(os.sched_getaffinity(0)), numerical_threads=1,
                   live_capture="NOT_RUN_OWNER_LOCAL_TEST_REQUIRED", independent_music_accuracy="NOT_RUN")
    return {"summary": summary, "receipts": receipts, "rankings": rankings}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="New private report, outside Git")
    args = parser.parse_args()
    core.require(not args.report.exists() and not core.inside_git(args.report),
                 "PRIVATE_NEW_REPORT_REQUIRED")
    result = run(args.manifest, args.index_dir)
    fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(result["summary"], indent=2))
