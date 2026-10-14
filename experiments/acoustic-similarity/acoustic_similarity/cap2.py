"""One authorized, bounded GMD cap2 run. No acquisition or fitting on import."""
import argparse
import base64
import csv
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np
import soundfile as sf

from .data import digest, file_hash, require, write_new
from .diagnostics import ARTIFACT_SHA, components, load_archive
from .features import code_hash
from .groove import MIDI_SHA, RangeZip, sha
from .model import fit_head
from .rhythm import (FEATURE_SCHEMA, TARGET_SCHEMA, SCHEMA, WINDOW_BEATS,
                     contrastive_arrays, make_triplets, midi_events, midi_target,
                     rhythm_features, validate_dataset)

BASE_HEAD = "0d8955f1788521f6458a64ceea3ba7db8e09b9ba"
PLAN_SHA = "3b1167534a85af7b043b792db8b1b2160b2d3c48aad33803d518510ce3c2d346"
RUN_NUMBER = "9"
AUTHORIZATION = "cap2-2026-10-14-v2"
OUTPUT = "runs/groove-cap2-v2"
LIMIT = 42 * 1024**2
RESERVE = 2 * 1024**2
INPUT_BYTES = 382152
SOURCE_BYTES = 40834108
BUNDLE_LIMIT = 64 * 1024
LOG_DOWNLOAD_LIMIT = 256 * 1024
EXPECTED_IDS = ("drummer6/session2/3", "drummer6/session3/6", "drummer6/session3/7")
SETTINGS = {"epochs": 300, "lr": .1, "regularization": .01, "logit_bound": float(np.log(2)/2)}
ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "validation/groove-diagnostics-v1/next-run-proposal.json"
ARTIFACT = ROOT / "validation/groove-cpu-v1/artifacts.zip"


def inputs():
    plan = json.loads(PLAN.read_text())
    require(digest(plan) == PLAN_SHA and plan["training"]["input_artifact_sha256"] == ARTIFACT_SHA,
            "Frozen cap2 proposal/input changed")
    require(plan["budget"]["authorized_limit_if_approved_bytes"] == LIMIT and
            SOURCE_BYTES + INPUT_BYTES + RESERVE <= LIMIT, "Insufficient reserved transfer budget")
    dev, _, integrity, old, _ = load_archive(ARTIFACT)
    require(sum(t["split"] == "train" for t in dev["triplets"]) == 332 and
            sum(r["split"] == "train" for r in dev["rows"]) == 140, "Frozen training cohort changed")
    return plan, dev, integrity, old


def validate_annotations(rows, old):
    require({r["original_id"] for r in rows} == set(EXPECTED_IDS), "Need exactly three prescribed originals")
    require(len({r["id"] for r in rows}) == len(rows), "Duplicate bar")
    old_midi = {r["midi_sha256"] for r in old.values()}
    old_drummers = {r["drummer"] for r in old.values()}
    identities = {}
    for r in rows:
        require(r["original_id"] not in old and r["drummer"] == "drummer6" and r["drummer"] not in old_drummers
                and r["midi_sha256"] not in old_midi, "Original/performer/MIDI intersects previous splits")
        require(r["bpm"] == 88 and r["split"] == "test" and r["start_beat"] in WINDOW_BEATS and
                r["id"] == f"{r['original_id']}#beat{r['start_beat']}", "Unreviewed tempo/window")
        require(identities.setdefault(r["midi_sha256"], r["original_id"]) == r["original_id"], "Duplicate MIDI originals")
        target = np.asarray(r["target"])
        require(target.shape == (144,) and np.isin(target, [0, 1]).all() and target.sum() >= 4,
                "Invalid performed MIDI target")
    trips = make_triplets(rows)
    require(len(trips) >= 20, "MIDI-only preflight failed: fewer than 20 comparisons; no audio permitted")
    require({next(r["original_id"] for r in rows if r["id"] == t[k]) for t in trips
             for k in ("anchor", "positive", "negative")} == set(EXPECTED_IDS), "Not all originals used")
    return trips


def preflight(raw, plan, old):
    require(len(raw) == plan["sources"]["midi_bytes"] and sha(raw) == MIDI_SHA, "Official MIDI archive mismatch")
    archive = zipfile.ZipFile(io.BytesIO(raw))
    metadata_raw = archive.read("groove/info.csv")
    metadata = {r["id"]: r for r in csv.DictReader(io.StringIO(metadata_raw.decode()))}
    rows, excluded, members = [], [], []
    for item in plan["new_test"]["records"]:
        r = item["metadata"]
        require(metadata.get(r["id"]) == r and r["bpm"] == "88" and r["time_signature"] == "4-4",
                "Metadata does not match prescribed cohort")
        annotation = archive.read("groove/" + r["midi_filename"])
        events = midi_events(annotation, 88)
        members.append({"original_id": r["id"], "midi_sha256": sha(annotation), "midi_bytes": len(annotation),
                        "midi_member": r["midi_filename"], "audio_member": item["zip_member"]})
        for beat in WINDOW_BEATS:
            target = midi_target(events, beat)
            if sum(target) < 4:
                excluded.append({"original_id": r["id"], "start_beat": beat, "reason": "fewer than four MIDI cells"})
                continue
            rows.append({"id": f"{r['id']}#beat{beat}", "original_id": r["id"], "drummer": r["drummer"],
                         "split": "test", "bpm": 88, "start_beat": beat, "midi_sha256": sha(annotation),
                         "genre": r["style"].split("/")[0], "target": target})
    trips = validate_annotations(rows, old)
    require(digest(trips) == "9b05777ec3cfa5ff727c55489a65bf60b0b0cdbf748f85f56a04fae59a971480",
            "Prescribed preflight comparisons changed")
    return {"status": "PASS", "plan_sha256": PLAN_SHA, "midi_archive_sha256": MIDI_SHA,
            "metadata_sha256": sha(metadata_raw), "members": members, "rows": rows, "triplets": trips,
            "triplets_sha256": digest(trips), "excluded": excluded,
            "counts": {"originals": len(members), "bars": len(rows), "triplets": len(trips)},
            "overlap_originals_performers_midi": "PASS", "audio_hash_overlap": "NOT RUN until acquisition"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class BoundedSource:
    """One request per range, fixed official sources, no redirects/retries/full archive."""
    def __init__(self, plan, receipt):
        self.plan = plan["sources"]
        self.records = plan["new_test"]["records"]
        self.receipt_path = Path(receipt)
        self.received, self.requests, self.seen = 0, [], set()
        self.opener = urllib.request.build_opener(NoRedirect())

    def snapshot(self):
        return {"received_source_bytes": self.received, "source_budget_bytes": SOURCE_BYTES,
                "training_artifact_bytes_charged": INPUT_BYTES, "reserved_transport_output_bytes": RESERVE,
                "total_budget_bytes": LIMIT, "requests": self.requests, "retries": 0}

    def fetch(self, url, size, start=None):
        require(type(size) is int and 0 < size <= 16*1024**2 and
                self.received+size <= SOURCE_BYTES and self.received+size+INPUT_BYTES+RESERVE <= LIMIT,
                "Transfer budget exhausted before request")
        source = self.plan
        if start is None:
            require(url == source["midi_url"] and size == source["midi_bytes"], "Unapproved source request")
        else:
            directory = (start, size) == (source["directory_offset"], source["directory_bytes"])
            member = any(r["header_offset"] <= start and start+size <=
                         r["header_offset"]+30+r["member_name_read_bytes"]+1024+r["compressed_bytes"] for r in self.records)
            require(url == source["audio_url"] and (directory or member), "Unapproved audio range")
        key = (url, start, size)
        require(key not in self.seen, "Repeated request prohibited")
        self.seen.add(key)
        entry = {"url": url, "start": start, "requested_bytes": size, "received_bytes": 0, "status": "STARTED"}
        self.requests.append(entry)
        headers = {"Accept-Encoding": "identity"}
        if start is not None:
            headers.update({"Range": f"bytes={start}-{start+size-1}", "If-Match": source["audio_etag"]})
        try:
            request = urllib.request.Request(url, headers=headers)
            with self.opener.open(request, timeout=30) as response:
                require(response.geturl() == url and response.status == (200 if start is None else 206),
                        "Unexpected redirect/status; no fallback permitted")
                require(int(response.headers.get("Content-Length", -1)) == size, "Unexpected response size")
                if start is not None:
                    require(response.headers.get("ETag") == source["audio_etag"] and
                            response.headers.get("Content-Range") == f"bytes {start}-{start+size-1}/{source['audio_bytes']}",
                            "Pinned archive/range changed")
                chunks = []
                while entry["received_bytes"] < size:
                    chunk = response.read(min(1024**2, size-entry["received_bytes"]))
                    require(chunk, "Truncated source response")
                    entry["received_bytes"] += len(chunk)
                    self.received += len(chunk)
                    chunks.append(chunk)
                entry["status"] = "PASS"
                return b"".join(chunks)
        except Exception:
            entry["status"] = "FAIL"
            raise
        finally:
            self.receipt_path.write_text(json.dumps(self.snapshot(), indent=2)+"\n")


def new_audio(client, plan, annotations, old):
    source = plan["sources"]
    directory = client.fetch(source["audio_url"], source["directory_bytes"], source["directory_offset"])
    require(sha(directory) == source["directory_sha256"], "Archive directory mismatch")
    archive = zipfile.ZipFile(RangeZip(client, directory))
    old_audio = {r["audio_sha256"] for r in old.values()}
    observed_audio, rows, originals = set(), [], []
    for item in plan["new_test"]["records"]:
        entry = archive.getinfo(item["zip_member"])
        require((entry.header_offset, entry.compress_size, entry.file_size, entry.CRC) ==
                (item["header_offset"], item["compressed_bytes"], item["uncompressed_bytes"], item["crc32"]),
                "Pinned member changed")
        require(entry.file_size <= 64*1024**2, "Uncompressed audio exceeds bound")
    for item in plan["new_test"]["records"]:
        audio = archive.read(item["zip_member"])
        audio_sha = sha(audio)
        require(audio_sha not in old_audio | observed_audio, "Duplicate audio: refusing evaluation")
        observed_audio.add(audio_sha)
        oid = item["metadata"]["id"]
        originals.append({"original_id": oid, "audio_sha256": audio_sha, "wav_member": item["zip_member"],
                          "uncompressed_bytes": len(audio), "crc32": item["crc32"]})
        with sf.SoundFile(io.BytesIO(audio)) as stream:
            require(stream.channels in (1, 2), "Unexpected audio channels")
            for row in annotations["rows"]:
                if row["original_id"] != oid:
                    continue
                start = round(row["start_beat"]*60/88*stream.samplerate)
                count = round(4*60/88*stream.samplerate)
                stream.seek(start)
                samples = stream.read(count, dtype="float32", always_2d=True).mean(axis=1)
                require(len(samples) == count, "Short audio for prescribed window")
                rows.append({**row, "audio_sha256": audio_sha,
                             "features": rhythm_features(samples, stream.samplerate, 88)})
    dataset = {"schema": SCHEMA, "feature_schema": FEATURE_SCHEMA, "target_schema": TARGET_SCHEMA,
               "kind": "real-performed-midi", "plan_sha256": PLAN_SHA, "midi_archive_sha256": MIDI_SHA,
               "rows": rows, "triplets": annotations["triplets"], "excluded_bars": annotations["excluded"]}
    validate_dataset(dataset)
    require(client.received == SOURCE_BYTES, "Unexpected aggregate source byte count")
    return dataset, originals


def counts(margins):
    margins = np.asarray(margins)
    ties = np.abs(margins) <= 1e-12
    good = (~ties) & (margins < 0)
    n, t, c = len(margins), int(ties.sum()), int(good.sum())
    require(n > 0, "Empty evaluation")
    return {"comparisons": n, "correct": c, "ties": t, "incorrect": n-c-t, "accuracy": (c+.5*t)/n}


def score(dataset, split, weights):
    X, trips = contrastive_arrays(dataset, split)
    b, w = X.mean(axis=1), X @ weights
    lookup = {r["id"]: r for r in dataset["rows"]}
    component = components(dataset["rows"], trips)
    result = {"uniform": counts(b), "cap2": counts(w), "by_original": [], "by_component": []}
    result["delta_accuracy"] = result["cap2"]["accuracy"]-result["uniform"]["accuracy"]
    result["improvement"] = "IMPROVED ON THIS COHORT" if result["delta_accuracy"] > 0 else "TIED" if result["delta_accuracy"] == 0 else "WORSE"
    for oid in sorted({lookup[t[k]]["original_id"] for t in trips for k in ("anchor", "positive", "negative")}):
        mask = np.array([any(lookup[t[k]]["original_id"] == oid for k in ("anchor", "positive", "negative")) for t in trips])
        anchored = np.array([lookup[t["anchor"]]["original_id"] == oid for t in trips])
        result["by_original"].append({"original_id": oid, "touching_uniform": counts(b[mask]), "touching_cap2": counts(w[mask]),
                                      "anchor_uniform": counts(b[anchored]) if anchored.any() else None,
                                      "anchor_cap2": counts(w[anchored]) if anchored.any() else None})
    for key in sorted({component[t["anchor"]] for t in trips}):
        mask = np.array([component[t["anchor"]] == key for t in trips])
        result["by_component"].append({"component": key, "originals": sorted({lookup[t[k]]["original_id"]
                     for t, keep in zip(trips, mask) if keep for k in ("anchor", "positive", "negative")}),
                     "uniform": counts(b[mask]), "cap2": counts(w[mask])})
    result["triplets"] = [{**t, "uniform_margin": float(b[i]), "cap2_margin": float(w[i])} for i, t in enumerate(trips)]
    return result


def guard(env, event, head, parent):
    require(env.get("CAP2_AUTHORIZATION") == AUTHORIZATION and
            env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_RUN_NUMBER") == RUN_NUMBER and
            env.get("GITHUB_RUN_ATTEMPT") == "1" and env.get("GITHUB_JOB") == "cap2-pilot" and
            env.get("GITHUB_REPOSITORY") == "zinverno/yanjaro" and env.get("GITHUB_EVENT_NAME") == "pull_request" and
            env.get("GITHUB_WORKFLOW_REF", "").startswith("zinverno/yanjaro/.github/workflows/acoustic-similarity.yml@"),
            "Cap2 allowed only in the one authorized workflow run/attempt/job")
    pr = event.get("pull_request", {})
    require(event.get("number") == 10 and event.get("action") == "synchronize" and
            pr.get("head", {}).get("repo", {}).get("full_name") == "zinverno/yanjaro" and
            pr.get("head", {}).get("ref") == "experiment/acoustic-similarity-v01" and
            pr.get("head", {}).get("sha") == head == env.get("SOURCE_COMMIT") and parent == BASE_HEAD,
            "Wrong PR, source commit, or authorized parent")
    require(all(env.get(k) == "2" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS")),
            "Two computational threads required")


def bundle(output):
    names = {"preflight.json", "model.json", "metrics.json", "new-test.json", "provenance.json",
             "resources.json", "acquisition.json", "status.json"}
    files = sorted(output.glob("*.json"))
    require({p.name for p in files} <= names, "Unexpected output; refusing to publish")
    hashes = {p.name: file_hash(p) for p in files}
    write_new(output / "hashes.json", hashes)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.glob("*.json")):
            archive.writestr(path.name, path.read_bytes())
    raw = buffer.getvalue()
    require(len(raw) <= BUNDLE_LIMIT, "Result bundle exceeds reserved transfer bound")
    (output / "artifacts.zip").write_bytes(raw)
    encoded = base64.b64encode(raw).decode("ascii")
    # Native workflow logs avoid artifact SDK automatic HTTP retries. One bounded ZIP, no raw audio.
    print(f"CAP2_RESULT_START sha256={sha(raw)} bytes={len(raw)} encoded_bytes={len(encoded)}", flush=True)
    for i in range(0, len(encoded), 4000):
        print("CAP2_RESULT_DATA " + encoded[i:i+4000], flush=True)
    print("CAP2_RESULT_END", flush=True)
    print(json.dumps({"artifact_sha256": sha(raw), "artifact_bytes": len(raw), "encoded_result_bytes": len(encoded)}), flush=True)


def run():
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Real cap2 run requires the authorized Actions job")
    repo = ROOT.parents[1]
    head, parent = (subprocess.check_output(["git", "rev-parse", ref], cwd=repo).decode().strip() for ref in ("HEAD", "HEAD^"))
    event = json.loads(Path(os.environ.get("GITHUB_EVENT_PATH", "/nonexistent-cap2-event")).read_text())
    guard(os.environ, event, head, parent)
    require(0 < resource.getrlimit(resource.RLIMIT_AS)[0] <= 4*1024**3 and
            0 < resource.getrlimit(resource.RLIMIT_CPU)[0] <= 600, "Missing memory/CPU limits")
    def deadline(signum, frame):
        raise TimeoutError("Execution limit reached")
    signal.signal(signal.SIGTERM, deadline)
    signal.signal(signal.SIGXCPU, deadline)
    resource.setrlimit(resource.RLIMIT_CPU, (590, 600))
    output = ROOT / OUTPUT
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.monotonic(), time.process_time()
    status = {"stage": "inputs", "status": "STARTED", "training_calls": 0, "test_evaluations": 0}
    client = None
    fit_seconds = None
    try:
        plan, dev, integrity, old = inputs()
        client = BoundedSource(plan, output / "acquisition.json")
        status["stage"] = "midi_preflight"
        raw = client.fetch(plan["sources"]["midi_url"], plan["sources"]["midi_bytes"])
        annotations = preflight(raw, plan, old)
        write_new(output / "preflight.json", annotations)
        status["stage"] = "audio_acquisition_and_features"
        dataset, originals = new_audio(client, plan, annotations, old)
        write_new(output / "new-test.json", dataset)
        X, train_trips = contrastive_arrays(dev, "train")
        require(X.shape == (332, 128), "Training array changed")
        status["stage"] = "training"
        status["training_calls"] = 1
        fit_started = time.monotonic()
        weights, loss = fit_head(X, np.zeros(len(X)), **SETTINGS)
        fit_seconds = time.monotonic()-fit_started
        require(max(weights)/min(weights) <= 2+1e-12, "Concentration constraint failed")
        model = {"schema": "yanjaro.rhythm-midi-cap2-head.v0.1", "version": "0.1.1-cap2-research",
                 "kind": "real-performed-midi", "status": "TRAINED RESEARCH PILOT - NOT A SONG SIMILARITY MODEL",
                 "aspect": "rhythm", "encoder": None, "feature_schema": FEATURE_SCHEMA, "target_schema": TARGET_SCHEMA,
                 "weights": weights, "training_loss": loss, "settings": {**SETTINGS, "margin": .05, "temperature": .1},
                 "input_artifact_sha256": ARTIFACT_SHA, "training_source_dataset_sha256": integrity["dataset_canonical_sha256"],
                 "training_rows_sha256": digest([r for r in dev["rows"] if r["split"] == "train"]),
                 "training_triplets_sha256": digest(train_trips), "new_test_dataset_sha256": digest(dataset),
                 "plan_sha256": PLAN_SHA, "code_sha256": code_hash(), "source_commit": head,
                 "training_bars": 140, "training_triplets": 332,
                 "github_run_id": os.environ["GITHUB_RUN_ID"], "github_run_number": RUN_NUMBER, "github_run_attempt": "1"}
        write_new(output / "model.json", model)  # Freeze weights before either held-out evaluation.
        status["stage"] = "evaluation"
        validation = score(dev, "validation", np.asarray(weights))
        status["test_evaluations"] = 1
        test = score(dataset, "test", np.asarray(weights))
        write_new(output / "metrics.json", {"status": "PASS: measurements completed", "validation": validation, "new_test": test,
                   "old_test": "NOT RUN; previous drummer8 unchanged", "quality": "PASS on this cohort only" if test["delta_accuracy"] > 0 else "FAIL: no improvement",
                   "population_improvement": "NOT ESTABLISHED: one performer, three connected originals"})
        write_new(output / "provenance.json", {"plan": plan, "plan_sha256": PLAN_SHA, "original_artifact_integrity": integrity,
                   "authorization_id": AUTHORIZATION, "output_binding": OUTPUT,
                   "new_originals": originals, "midi_sources": annotations["members"], "audio_hash_overlap": "PASS",
                   "training_uses_only_original_332_triplets": True, "old_test_used": False,
                   "acquisition": client.snapshot(), "authorization": "User explicitly authorized one cap2 run under 42 MiB, 10 minutes, CPU only",
                   "parent_commit": BASE_HEAD, "training_source_commit": head,
                   "output_transport": "Single base64 ZIP in native workflow log; no artifact SDK or application retries"})
        status.update({"stage": "complete", "status": "PASS"})
    except Exception as exc:
        status.update({"status": "FAIL", "error_type": type(exc).__name__,
                       "reason": str(exc) if isinstance(exc, ValueError) else "Operation failed; stopped without retry"})
    finally:
        write_new(output / "status.json", status)
        write_new(output / "resources.json", {"wall_seconds": time.monotonic()-started,
                  "cpu_seconds": time.process_time()-cpu_started, "process_cpu_seconds": time.process_time(),
                  "user_cpu_seconds": resource.getrusage(resource.RUSAGE_SELF).ru_utime,
                  "system_cpu_seconds": resource.getrusage(resource.RUSAGE_SELF).ru_stime, "fit_seconds": fit_seconds,
                  "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                  "peak_virtual_mib": int(next(line.split()[1] for line in Path("/proc/self/status").read_text().splitlines()
                                               if line.startswith("VmPeak:")))/1024,
                  "virtual_memory_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
                  "cpu_limit_seconds": resource.getrlimit(resource.RLIMIT_CPU),
                  "received_source_bytes": client.received if client else 0, "input_artifact_bytes_charged": INPUT_BYTES,
                  "reserved_transport_output_bytes": RESERVE, "transfer_limit_bytes": LIMIT,
                  "bundle_limit_bytes": BUNDLE_LIMIT, "log_download_limit_bytes": LOG_DOWNLOAD_LIMIT,
                  "gpu": False, "computational_threads": 2, "python": platform.python_version(),
                  "versions": {p: importlib.metadata.version(p) for p in ("numpy", "scipy", "soundfile", "mido")},
                  "github_run_id": os.environ["GITHUB_RUN_ID"], "github_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                  "source_commit": head})
        bundle(output)
    return 0 if status["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--midi-archive", type=Path, required=True)
    pre.add_argument("--output", type=Path, required=True)
    sub.add_parser("run")
    args = parser.parse_args()
    if args.command == "preflight":
        started, cpu = time.monotonic(), time.process_time()
        plan, _, integrity, old = inputs()
        result = preflight(args.midi_archive.read_bytes(), plan, old)
        result["original_artifact_integrity"] = integrity
        result["resources"] = {"source_download_bytes": 0, "wall_seconds": time.monotonic()-started,
                               "cpu_seconds": time.process_time()-cpu,
                               "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024}
        write_new(args.output, result)
        print(json.dumps({"status": result["status"], "counts": result["counts"], "triplets_sha256": result["triplets_sha256"]}))
    else:
        raise SystemExit(run())


if __name__ == "__main__":
    main()
