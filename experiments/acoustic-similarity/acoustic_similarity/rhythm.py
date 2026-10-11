"""CPU rhythm-only pilot: audio metric supervised by independent performed MIDI."""
import argparse
from collections import defaultdict
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import resource
import time

import mido
import numpy as np
from scipy import signal
import soundfile as sf

from .data import digest, is_hash, read_json, require, write_new
from .features import code_hash
from .groove import SCHEMA, acquire, sha
from .model import fit_head

MODEL_SCHEMA = "yanjaro.rhythm-midi-head.v0.1"
FEATURE_SCHEMA = "audio-flux-4bands-16phase-ac64-beat-normalized.v1"
TARGET_SCHEMA = "performed-midi-9drums-16phase-binary-jaccard.v1"
DRUMS = [{36}, {38, 40, 37}, {48, 50}, {45, 47}, {43, 58},
         {46, 26}, {42, 22, 44}, {49, 55, 57, 52}, {51, 59, 53}]
WINDOW_BEATS = (4, 8, 12, 16)


def midi_events(raw, bpm):
    midi = mido.MidiFile(file=io.BytesIO(raw))
    require(midi.type in (0, 1) and midi.ticks_per_beat > 0, "Unsupported MIDI timing")
    ticks, events, tempos = 0, [], []
    for message in mido.merge_tracks(midi.tracks):
        ticks += message.time
        if message.type == "set_tempo":
            tempos.append(60_000_000 / message.tempo)
        if message.type == "time_signature":
            require((message.numerator, message.denominator) == (4, 4), "MIDI meter differs from cohort")
        if message.type == "note_on" and message.velocity > 0:
            require(message.channel == 9, "Non-drum MIDI channel")
            family = next((i for i, pitches in enumerate(DRUMS) if message.note in pitches), None)
            require(family is not None, "Unmapped drum note")
            events.append((ticks / midi.ticks_per_beat, family))
    require(events and tempos and all(abs(t - bpm) < .01 for t in tempos), "MIDI/metadata tempo mismatch")
    return events


def midi_target(events, start_beat):
    grid = np.zeros((9, 16), dtype=int)
    for beat, family in events:
        if start_beat <= beat < start_beat + 4:
            grid[family, round((beat - start_beat) * 4) % 16] = 1
    return grid.ravel().tolist()


def rhythm_features(y, sr, bpm):
    """Beat-normalized spectral flux. No MIDI hits, genre, or drummer enter features."""
    require(40 <= bpm <= 260 and 8000 <= sr <= 96000, "Unsupported tempo/sample rate")
    y = np.asarray(y, dtype=float)
    require(y.ndim == 1 and len(y) >= sr * .8 and np.isfinite(y).all() and
            np.max(np.abs(y)) > 1e-5, "Empty, silent or nonfinite audio")
    if sr != 16000:
        from math import gcd
        divisor = gcd(sr, 16000)
        y = signal.resample_poly(y, 16000 // divisor, sr // divisor)
    frequencies, times, spectrum = signal.stft(y, fs=16000, nperseg=512, noverlap=384,
                                              boundary="zeros", padded=False)
    magnitude = np.abs(spectrum)
    flux = np.maximum(np.diff(magnitude, prepend=magnitude[:, :1], axis=1), 0)
    bands = np.array([flux[(frequencies >= low) & (frequencies < high)].sum(axis=0)
                      for low, high in ((0, 200), (200, 800), (800, 3000), (3000, 8001))])
    # Seconds become beat phase; BPM is never a learnable scalar or a target.
    phase = np.rint(times * bpm / 60 * 4).astype(int) % 16
    grid = np.zeros((4, 16))
    for i in range(16):
        if np.any(phase == i):
            grid[:, i] = bands[:, phase == i].max(axis=1)
    grid /= np.maximum(np.linalg.norm(grid, axis=1, keepdims=True), 1e-10)
    onset = bands.sum(axis=0)
    onset -= onset.mean()
    ac = signal.correlate(onset, onset, mode="full", method="fft")[len(onset)-1:]
    ac /= max(float(ac[0]), 1e-10)
    profile = np.interp(np.linspace(1/16, 4, 64), np.arange(len(ac)) * 128 / 16000 * bpm / 60, ac)
    result = np.r_[grid.ravel(), profile]
    require(result.shape == (128,) and np.isfinite(result).all(), "Invalid rhythm features")
    return result.tolist()


def annotation_distance(a, b):
    a, b = np.asarray(a, dtype=bool), np.asarray(b, dtype=bool)
    return 1 - float(np.logical_and(a, b).sum()) / max(1, int(np.logical_or(a, b).sum()))


def make_triplets(rows):
    """At most four deterministic, margin-separated MIDI comparisons per anchor."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["split"], row["drummer"], row["bpm"]].append(row)
    result = []
    for group in groups.values():
        for a in group:
            candidates = [r for r in group if r["original_id"] != a["original_id"]]
            distances = {r["id"]: annotation_distance(a["target"], r["target"]) for r in candidates}
            comparisons = []
            for p in candidates:
                for n in candidates:
                    gap = distances[n["id"]] - distances[p["id"]]
                    if p["original_id"] != n["original_id"] and gap >= .15:
                        comparisons.append((gap, p, n))
            for gap, p, n in sorted(comparisons, key=lambda t: (-t[0], t[1]["id"], t[2]["id"]))[:4]:
                result.append({"anchor": a["id"], "positive": p["id"], "negative": n["id"],
                               "midi_margin": gap, "split": a["split"],
                               "source": TARGET_SCHEMA})
    return result


def validate_dataset(dataset):
    require(dataset.get("schema") == SCHEMA and dataset.get("feature_schema") == FEATURE_SCHEMA and
            dataset.get("target_schema") == TARGET_SCHEMA and dataset.get("kind") == "real-performed-midi",
            "Not the independently annotated GMD experiment")
    require(is_hash(dataset.get("plan_sha256")) and dataset.get("midi_archive_sha256") ==
            "651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e",
            "Missing official provenance")
    rows = dataset["rows"]
    lookup, groups = {}, {}
    for r in rows:
        require(r["id"] not in lookup and r["split"] in ("train", "validation", "test"), "Duplicate ID/invalid split")
        lookup[r["id"]] = r
        for field in ("drummer", "original_id", "audio_sha256", "midi_sha256"):
            require(bool(r[field]), "Missing source identity")
            key = (field, r[field])
            require(key not in groups or groups[key] == r["split"], "Original/performer/duplicate source crosses split")
            groups[key] = r["split"]
        require(is_hash(r["audio_sha256"]) and is_hash(r["midi_sha256"]), "Missing source hashes")
        require(r["start_beat"] in WINDOW_BEATS and r["id"] == f"{r['original_id']}#beat{r['start_beat']}",
                "Unidentified derivative")
        require(type(r["bpm"]) is int and 40 <= r["bpm"] <= 260, "Invalid annotated BPM")
        v, target = np.asarray(r["features"]), np.asarray(r["target"])
        require(v.shape == (128,) and np.isfinite(v).all() and np.max(np.abs(v)) <= 1.000001,
                "Invalid audio features")
        require(target.shape == (144,) and np.isin(target, [0, 1]).all() and target.sum() >= 4,
                "Invalid MIDI structure annotation")
    # Recompute labels from MIDI annotations, never accept external similarity scores/reactions.
    expected = make_triplets(rows)
    require(dataset["triplets"] == expected, "Triplets differ from independent MIDI targets")
    for t in expected:
        a, p, n = (lookup[t[k]] for k in ("anchor", "positive", "negative"))
        require(len({r["original_id"] for r in (a, p, n)}) == 3 and
                len({r["bpm"] for r in (a, p, n)}) == 1, "Recording/tempo shortcut")
    return lookup


def contrastive_arrays(dataset, split):
    lookup = {r["id"]: r for r in dataset["rows"]}
    selected = [t for t in dataset["triplets"] if t["split"] == split]
    values = []
    for t in selected:
        a, p, n = (np.asarray(lookup[t[k]]["features"]) for k in ("anchor", "positive", "negative"))
        values.append((a-p)**2 - (a-n)**2)
    return np.asarray(values), selected


def evaluate(dataset, split, weights):
    x, triplets = contrastive_arrays(dataset, split)
    require(len(triplets) > 0, "No independent comparisons for " + split)
    lookup = {r["id"]: r for r in dataset["rows"]}
    baseline, learned = x.mean(axis=1), x @ weights
    def accuracy(values):
        return float(np.mean(np.where(np.abs(values) <= 1e-12, .5, values < 0)))
    metrics = {"triplets": len(triplets), "baseline_accuracy": accuracy(baseline),
               "learned_accuracy": accuracy(learned), "tempo_only_accuracy": .5,
               "groups": [], "slices": {}}
    metrics["delta"] = metrics["learned_accuracy"] - metrics["baseline_accuracy"]
    metrics["observed_result"] = "IMPROVED" if metrics["delta"] > 0 else "WORSE" if metrics["delta"] < 0 else "TIED"
    for drummer, bpm in sorted({(lookup[t["anchor"]]["drummer"], lookup[t["anchor"]]["bpm"]) for t in triplets}):
        mask = np.array([(lookup[t["anchor"]]["drummer"], lookup[t["anchor"]]["bpm"]) == (drummer, bpm) for t in triplets])
        metrics["groups"].append({"drummer": drummer, "bpm": bpm, "triplets": int(mask.sum()),
                                   "baseline_accuracy": accuracy(baseline[mask]), "learned_accuracy": accuracy(learned[mask])})
    for name, condition in {
        "same_genre_different_rhythm": lambda a, p, n: a["genre"] == n["genre"],
        "different_genre_similar_rhythm": lambda a, p, n: a["genre"] != p["genre"],
    }.items():
        mask = np.array([condition(*(lookup[t[k]] for k in ("anchor", "positive", "negative"))) for t in triplets])
        metrics["slices"][name] = {"triplets": int(mask.sum()), "status": "PASS" if mask.any() else "NOT RUN",
               "baseline_accuracy": accuracy(baseline[mask]) if mask.any() else None,
               "learned_accuracy": accuracy(learned[mask]) if mask.any() else None}
    metrics["slices"]["same_tempo_different_instrumentation"] = {"status": "NOT RUN", "reason": "GMD uses a single TD-11 kit"}
    metrics["population_improvement"] = "NOT ESTABLISHED: one held-out drummer per split; correlated bars/triplets"
    return metrics


def train_head(dataset):
    lookup = validate_dataset(dataset)
    counts = {}
    for split in ("train", "validation", "test"):
        rows = [r for r in lookup.values() if r["split"] == split]
        comparisons = [t for t in dataset["triplets"] if t["split"] == split]
        used = {t[k] for t in comparisons for k in ("anchor", "positive", "negative")}
        counts[split] = {"bars": len(rows), "originals": len({r["original_id"] for r in rows}),
                         "used_bars": len(used), "used_originals": len({lookup[i]["original_id"] for i in used}),
                         "drummers": sorted({lookup[i]["drummer"] for i in used}), "triplets": len(comparisons)}
        require(len(comparisons) >= (60 if split == "train" else 20) and
                counts[split]["used_originals"] >= (9 if split == "train" else 3), "Insufficient real GMD comparisons: " + split)
    require(len(counts["train"]["drummers"]) >= 3, "Need three independent training drummers")
    x, _ = contrastive_arrays(dataset, "train")
    weights, loss = fit_head(x, np.zeros(len(x)))
    return {"schema": MODEL_SCHEMA, "feature_schema": FEATURE_SCHEMA, "target_schema": TARGET_SCHEMA,
            "kind": "real-performed-midi", "version": "0.1.0", "aspect": "rhythm", "encoder": None,
            "status": "TRAINED RESEARCH PILOT - NOT A SONG SIMILARITY MODEL",
            "weights": weights, "dataset_sha256": digest(dataset), "plan_sha256": dataset["plan_sha256"],
            "code_sha256": code_hash(), "training_loss": loss, "counts": counts,
            "settings": {"epochs": 300, "learning_rate": .1, "regularization": .01, "margin": .05,
                         "temperature": .1, "selection": "fixed before test; no validation tuning"},
            "baseline": "same 128 beat-normalized audio features, uniform diagonal weights",
            "metrics": {s: evaluate(dataset, s, np.asarray(weights)) for s in ("validation", "test")}}


def run(plan_path, output):
    require(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_RUN_ATTEMPT") == "2",
            "Real pilot is restricted to the single authorized remote Actions attempt 2")
    plan = read_json(plan_path)
    # Pin the reviewed selection and acquisition parameters, not just self-declared rights.
    require(digest(plan) == COHORT_DIGEST, "Unreviewed cohort; create a separately reviewed experiment")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.monotonic(), time.process_time()
    rows, originals, energy, excluded = [], [], [], []
    fit_seconds = None
    try:
        for item, audio, annotation in acquire(plan, output):
            r = item["metadata"]
            bpm = int(r["bpm"])
            events = midi_events(annotation, bpm)
            source = {"original_id": r["id"], "drummer": r["drummer"], "split": item["split"],
                      "audio_sha256": sha(audio), "midi_sha256": sha(annotation), "bpm": bpm,
                      "genre": r["style"].split("/")[0]}
            originals.append({**source, "wav_member": item["zip_member"], "midi_member": r["midi_filename"]})
            with sf.SoundFile(io.BytesIO(audio)) as f:
                require(f.channels in (1, 2), "Unexpected audio channels")
                for beat in WINDOW_BEATS:
                    target = midi_target(events, beat)
                    if sum(target) < 4:
                        excluded.append({"original_id": r["id"], "start_beat": beat,
                                         "reason": "fewer than 4 occupied MIDI cells", "cells": sum(target)})
                        continue
                    start, count = round(beat * 60 / bpm * f.samplerate), round(4 * 60 / bpm * f.samplerate)
                    f.seek(start)
                    y = f.read(count, dtype="float32", always_2d=True).mean(axis=1)
                    require(len(y) == count, "Short GMD audio")
                    features = rhythm_features(y, f.samplerate, bpm)
                    rows.append({**source, "id": f"{r['id']}#beat{beat}", "start_beat": beat,
                                 "features": features, "target": target})
                    energy.append({"id": rows[-1]["id"], "rms_dbfs": float(20*np.log10(max(1e-8, np.sqrt(np.mean(y**2))))),
                                   "peak_dbfs": float(20*np.log10(max(1e-8, np.max(np.abs(y)))))})
        dataset = {"schema": SCHEMA, "feature_schema": FEATURE_SCHEMA, "target_schema": TARGET_SCHEMA,
                   "kind": "real-performed-midi", "plan_sha256": digest(plan), "midi_archive_sha256": plan["midi_sha256"],
                   "rows": rows, "triplets": make_triplets(rows), "excluded_bars": excluded}
        write_new(output / "dataset.json", dataset)
        write_new(output / "originals.json", originals)
        write_new(output / "energy-baseline.json", {"quality": "NOT RUN: no independent energy target", "measurements": energy})
        fit_started = time.monotonic()
        model = train_head(dataset)
        fit_seconds = time.monotonic() - fit_started
        write_new(output / "model.json", model)
        write_new(output / "metrics.json", model["metrics"])
        print(json.dumps({"counts": model["counts"], "metrics": model["metrics"]}, indent=2))
    finally:
        write_new(output / "resources.json", {"wall_seconds": time.monotonic()-started,
                   "cpu_seconds": time.process_time()-cpu_started,
                   "fit_and_evaluation_seconds": fit_seconds,
                   "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                   "python": platform.python_version(), "platform": platform.platform(),
                   "versions": {p: importlib.metadata.version(p) for p in ("numpy", "scipy", "soundfile", "mido")},
                   "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                   "source_commit": os.environ.get("SOURCE_COMMIT"), "gpu": False})


def search(audio_path, bpm, model, dataset, count=10):
    require(40 <= bpm <= 260 and Path(audio_path).stat().st_size <= 64 * 1024**2, "Invalid BPM/oversize query")
    require(model.get("schema") == MODEL_SCHEMA and model.get("feature_schema") == FEATURE_SCHEMA and
            model.get("kind") == "real-performed-midi" and model.get("dataset_sha256") == digest(dataset),
            "Incompatible or unbound model/catalog")
    validate_dataset(dataset)
    weights = np.asarray(model["weights"])
    require(weights.shape == (128,) and np.isfinite(weights).all() and (weights > 0).all() and
            abs(weights.sum()-1) < 1e-8, "Invalid weights")
    raw = Path(audio_path).read_bytes()
    query_sha = sha(raw)
    matches = [r for r in dataset["rows"] if r["audio_sha256"] == query_sha]
    require(matches and all(r["bpm"] == bpm for r in matches),
            "Pilot search accepts only hash-verified GMD originals and their annotated BPM; use the baseline CLI for other cleared audio")
    with sf.SoundFile(io.BytesIO(raw)) as f:
        require(f.channels in (1, 2), "Expected mono/stereo")
        f.seek(round(4*60/bpm*f.samplerate))
        frames = round(4*60/bpm*f.samplerate)
        y = f.read(frames, dtype="float32", always_2d=True).mean(axis=1)
        require(len(y) == frames, "Query must contain the complete second bar")
        vector = np.asarray(rhythm_features(y, f.samplerate, bpm))
    distances = defaultdict(list)
    for row in dataset["rows"]:
        if row["audio_sha256"] != query_sha:
            distances[row["original_id"]].append(float((vector-np.asarray(row["features"]))**2 @ weights))
    return sorted(({"original_id": key, "rhythm_distance": float(np.mean(values))} for key, values in distances.items()),
                  key=lambda r: (r["rhythm_distance"], r["original_id"]))[:count]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pilot = sub.add_parser("run")
    pilot.add_argument("--plan", required=True)
    pilot.add_argument("--output", required=True)
    query = sub.add_parser("search")
    query.add_argument("audio")
    query.add_argument("--bpm", type=int, required=True)
    query.add_argument("--model", required=True)
    query.add_argument("--catalog", required=True)
    args = parser.parse_args()
    if args.command == "run":
        run(args.plan, args.output)
    else:
        print(json.dumps(search(args.audio, args.bpm, read_json(args.model), read_json(args.catalog)), indent=2))


COHORT_DIGEST = "aa8977f3d79f91a7e086db8f0869b4228ba65e76d80d1220560fce8474b5a905"

if __name__ == "__main__":
    main()
