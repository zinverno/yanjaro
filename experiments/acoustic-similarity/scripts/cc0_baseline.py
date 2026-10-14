"""Re-audit only the ten already-local PR #9 originals; publish no audio/paths."""
import argparse
from pathlib import Path
import resource
import sys
import time

from acoustic_similarity.cli import search
from acoustic_similarity.data import SCHEMA, digest, file_hash, read_json, require, write_new
from acoustic_similarity.evaluate import evaluate
from acoustic_similarity.features import build_index

PR9_RECEIPT_SHA256 = "ee1fc59fc04967dbbbdcf634fa152adc713b6daf218e0baaf591338f0f7a64ea"


def run(private_root, previous_receipt, out):
    private_root, out = Path(private_root), Path(out)
    require(file_hash(previous_receipt) == PR9_RECEIPT_SHA256, "Expected frozen PR #9 public receipt")
    require(not out.exists(), "Output directory must be new")
    records = [r for r in read_json(previous_receipt)["records"] if r.get("downloaded") is True]
    require(len(records) == 10, "Expected exactly ten previously obtained originals")
    tracks = []
    for r in records:
        candidates = list((private_root / "originals").glob(r["id"] + ".*"))
        require(len(candidates) == 1, "Missing/ambiguous local original: " + r["id"])
        evidence = private_root / "evidence" / (r["id"] + ".html")
        require(r["license"] == "CC0-1.0" and r["rights_for_acquisition_verified"] is True and
                r["permissions"]["local_analysis"] is True, "Missing prior permission")
        require("creativecommons.org/publicdomain/zero/1.0" in evidence.read_text(), "Missing CC0 declaration")
        tracks.append({"id": r["id"], "artist_ids": [r["creator_id"]], "recording_group": r["id"],
            "split": "diagnostic", "path": str(candidates[0].resolve()), "sha256": r["source_sha256"],
            "start": r["start"], "seconds": r["seconds"],
            "rights": {"reviewed": True, "acquisition": True, "analysis": True, "training": False,
                       "remote": False, "license": "CC0-1.0", "source_url": r["source"],
                       "evidence_path": str(evidence.resolve()), "evidence_sha256": r["publication_evidence_sha256"],
                       "attribution": r["title"] + " — " + r["artist"], "verified_on": "2026-10-11",
                       "scope": "Recheck exact PR9 originals and evidence; local diagnostic DSP only"}})
    manifest = {"schema": SCHEMA, "kind": "real", "dataset_id": "pr9-ten-cc0-diagnostic-v1", "tracks": tracks}
    network_attempts = []
    def no_network(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            network_attempts.append(event)
            raise RuntimeError("Network prohibited during local audio audit")
    sys.addaudithook(no_network)
    start = time.perf_counter()
    index = build_index(manifest)
    elapsed = time.perf_counter() - start
    labels = {"schema": SCHEMA, "kind": "real", "dataset_sha256": digest(manifest),
              "purpose": "acoustic_similarity", "triplets": []}
    evaluation = evaluate(manifest, index, labels)
    rankings = {}
    for t in tracks:
        result = search(t["path"], manifest, index, top=3)
        rankings[t["id"]] = [{k: v for k, v in x.items() if k != "path"} for x in result["results"]]
    repeat = build_index(manifest)
    require(index["tracks"] == repeat["tracks"], "Feature extraction is not repeatable")
    out.mkdir(parents=True, mode=0o700)
    for name, data in (("manifest", manifest), ("index", index), ("labels", labels)):
        write_new(out / (name + ".json"), data)
    report = {"schema": SCHEMA, "checked_on": "2026-10-11", "kind": "real", "baseline": "DSP only",
              "input_receipt_sha256": PR9_RECEIPT_SHA256, "feature_schema": index["feature_schema"],
              "code_sha256": index["code_sha256"], "environment": index["environment"],
              "counts": {"recordings": len(tracks), "artist_groups": len({a for t in tracks for a in t["artist_ids"]}),
                         "reviewed_triplets": 0, "training_recordings": 0},
              "runtime": {"first_pass_seconds": elapsed, "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                          "python_socket_attempts": len(network_attempts), "analyzed_seconds": sum(t["seconds"] for t in tracks)},
              "checks": {"hashes_and_rights": "PASS", "extract_all": "PASS", "repeatability": "PASS",
                         "local_search_all_ten": "PASS", "frozen_encoder": "NOT RUN", "real_training": "NOT RUN",
                         "human_quality": "NOT RUN", "improvement": "NOT ESTABLISHED"},
              "records": [{"id": t["id"], "sha256": t["sha256"], "artist_ids": t["artist_ids"],
                           "source_url": t["rights"]["source_url"], "license": t["rights"]["license"],
                           "evidence_sha256": t["rights"]["evidence_sha256"], "start": t["start"], "seconds": t["seconds"],
                           "bpm": row["bpm"], "bpm_status": row["bpm_status"], "lab27": row["lab27"]}
                          for t, row in zip(tracks, index["tracks"])],
              "rankings_top3": rankings, "evaluation": evaluation,
              "warning": "Numeric proximity is diagnostic, not a human similarity label or quality result."}
    write_new(out / "baseline-report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--pr9-receipt", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    a = parser.parse_args()
    r = run(a.private_root, a.pr9_receipt, a.out)
    print(r["counts"], r["checks"], r["runtime"])
