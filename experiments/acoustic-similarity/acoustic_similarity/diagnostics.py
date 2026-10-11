"""Offline exploratory audit of the immutable first GMD run; never evaluates old test."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import resource
import subprocess
import time
import zipfile

import numpy as np

from .data import digest, file_hash, require, write_new
from .groove import MIDI_SHA, sha
from .model import contrastive_objective, fit_head
from .rhythm import (annotation_distance, contrastive_arrays, midi_events, midi_target,
                     rhythm_features, validate_dataset)

ARTIFACT_SHA = "72a1f4505afcc095d3ffaddd3cdc354cc1718c08861313fd91bfb6788b7fc79e"
TRAINING_COMMIT = "c9e37423b557fa4204edbf8167ce8620bc86536b"
ROLES = ("anchor", "positive", "negative")
# One declared exploratory grid, not an optimizer/search loop. Old test is inaccessible below load_archive.
CONFIGS = ("uniform", "original", "l2_0.1", "l2_1", "cap2", "flux_uniform", "ac_uniform",
           "mix_0.1", "mix_0.25", "mix_0.5")


def development_only(dataset):
    return {**dataset, "rows": [r for r in dataset["rows"] if r["split"] in ("train", "validation")],
            "triplets": [t for t in dataset["triplets"] if t["split"] in ("train", "validation")]}


def load_archive(path):
    path = Path(path)
    require(file_hash(path) == ARTIFACT_SHA, "First-run artifact SHA-256 mismatch")
    with zipfile.ZipFile(path) as archive:
        raw = {n: archive.read(n) for n in archive.namelist()}
    values = {n: json.loads(v) for n, v in raw.items()}
    dataset, model, sources = (values[n] for n in ("dataset.json", "model.json", "sources.json"))
    for name in ("model.json", "metrics.json", "resources.json"):
        require(raw[name] == (path.parent / name).read_bytes(), "External artifact copy changed: " + name)
    require(digest(dataset) == model["dataset_sha256"], "Features/labels do not match model")
    require(digest(sources["plan"]) == sources["plan_sha256"] == dataset["plan_sha256"] == model["plan_sha256"],
            "Source/cohort mismatch")
    preflight = json.loads((path.parent.parent / "groove-annotation-preflight.json").read_text())
    require(digest(dataset["triplets"]) == preflight["annotation_triplets_sha256"], "Pre-audio labels changed")
    require(sources["midi_archive_sha256"] == dataset["midi_archive_sha256"] == MIDI_SHA,
            "Official MIDI source changed")
    originals = {r["original_id"]: r for r in values["originals.json"]}
    owners = {}
    for row in dataset["rows"]:
        source = originals[row["original_id"]]
        for field in ("drummer", "original_id", "audio_sha256", "midi_sha256"):
            require(row[field] == source[field], "Row/source identity mismatch")
            key = (field, row[field])
            require(owners.setdefault(key, row["split"]) == row["split"], "Source crosses split")
    integrity = {"status": "PASS", "archive_sha256": ARTIFACT_SHA,
                 "members_sha256": {n: sha(v) for n, v in raw.items()},
                 "dataset_canonical_sha256": digest(dataset), "triplets_sha256": digest(dataset["triplets"]),
                 "feature_values_sha256": digest({r["id"]: r["features"] for r in dataset["rows"]}),
                 "target_values_sha256": digest({r["id"]: r["target"] for r in dataset["rows"]}),
                 "training_code_sha256": model["code_sha256"], "training_commit": TRAINING_COMMIT,
                 "full_audio_reextraction": "NOT RUN: originals not retained; hash binding is not re-extraction",
                 "old_test": "Only archive/hash/source identity checks; excluded before numeric diagnostics"}
    dev = development_only(dataset)
    validate_dataset(dev)
    return dev, np.asarray(model["weights"]), integrity, originals, sources


def verify_historical_code(repo, expected):
    prefix = "experiments/acoustic-similarity/acoustic_similarity/"
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", TRAINING_COMMIT, "--", prefix], cwd=repo).decode().splitlines()
    hashes = {Path(n).name: sha(subprocess.check_output(["git", "show", f"{TRAINING_COMMIT}:{n}"], cwd=repo))
              for n in names if n.endswith(".py") and "/" not in n[len(prefix):]}
    require(hashes and digest(hashes) == expected, "Historical training code mismatch (full Git history needed)")


def verify_midi(path, dev, originals, sources):
    require(file_hash(path) == MIDI_SHA, "Local MIDI archive hash mismatch")
    with zipfile.ZipFile(path) as archive:
        metadata = archive.read("groove/info.csv")
        require(sha(metadata) == sources["metadata_sha256"], "MIDI metadata mismatch")
        events = {}
        for row in dev["rows"]:
            oid = row["original_id"]
            if oid not in events:
                raw = archive.read("groove/" + originals[oid]["midi_member"])
                require(sha(raw) == row["midi_sha256"], "MIDI member mismatch")
                events[oid] = midi_events(raw, row["bpm"])
            require(midi_target(events[oid], row["start_beat"]) == row["target"], "Cached MIDI target mismatch")
    return {"status": "PASS", "originals": len(events), "bars": len(dev["rows"]), "old_test_read": False}


def correct(margins):
    margins = np.asarray(margins)
    return np.where(np.abs(margins) <= 1e-12, .5, margins < 0)


def describe(values):
    v = np.asarray(values, dtype=float)
    return {"n": len(v), "mean": float(v.mean()), "p10": float(np.quantile(v, .1)),
            "median": float(np.median(v)), "p90": float(np.quantile(v, .9))}


def components(rows, triplets):
    """Whole-original connected components of the triplet hypergraph, not IID bars."""
    lookup = {r["id"]: r for r in rows}
    parent = {r["original_id"]: r["original_id"] for r in rows}
    def root(a):
        while a != parent[a]:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for t in triplets:
        ids = [lookup[t[k]]["original_id"] for k in ROLES]
        for other in ids[1:]:
            parent[root(other)] = root(ids[0])
    members = defaultdict(list)
    for oid in parent:
        members[root(oid)].append(oid)
    canonical = {oid: min(group) for group in members.values() for oid in group}
    return {r["id"]: canonical[r["original_id"]] for r in rows}


def performer_folds(dev):
    require(all(r["split"] in ("train", "validation") for r in dev["rows"]), "Old test forbidden in diagnostics")
    rows = [r for r in dev["rows"] if r["split"] == "train"]
    lookup = {r["id"]: r for r in rows}
    trips = [t for t in dev["triplets"] if t["split"] == "train"]
    component = components(rows, trips)
    for drummer in sorted({r["drummer"] for r in rows}):
        held = np.array([lookup[t["anchor"]]["drummer"] == drummer for t in trips])
        fit_rows = [r for r in rows if r["drummer"] != drummer]
        held_rows = [r for r in rows if r["drummer"] == drummer]
        for field in ("drummer", "original_id", "audio_sha256", "midi_sha256"):
            require(not ({r[field] for r in fit_rows} & {r[field] for r in held_rows}), "CV source overlap")
        require(not ({component[r["id"]] for r in fit_rows} & {component[r["id"]] for r in held_rows}),
                "Connected triplets cross CV fold")
        for t, is_held in zip(trips, held):
            require(all((lookup[t[k]]["drummer"] == drummer) == is_held for k in ROLES), "Triplet crosses CV fold")
        require(held.any() and (~held).any(), "Empty CV fold")
        yield drummer, held, component


def ablation_weights(name, X):
    uniform = np.full(128, 1/128)
    if name == "uniform":
        return uniform
    if name in ("flux_uniform", "ac_uniform"):
        return np.r_[np.full(64, 1/64), np.zeros(64)] if name == "flux_uniform" else np.r_[np.zeros(64), np.full(64, 1/64)]
    settings = {"l2_0.1": {"regularization": .1}, "l2_1": {"regularization": 1.},
                "cap2": {"logit_bound": float(np.log(2)/2)}}
    require(name in CONFIGS, "Unknown exploratory configuration")
    learned = np.asarray(fit_head(X, np.zeros(len(X)), **settings.get(name, {}))[0])
    if name.startswith("mix_"):
        alpha = float(name.removeprefix("mix_"))
        return (1-alpha)*uniform + alpha*learned
    return learned


def cluster_score(scores, keys):
    return float(np.mean([np.mean(scores[np.array(keys) == k]) for k in sorted(set(keys))]))


def ablations(dev):
    X, trips = contrastive_arrays(dev, "train")
    V, _ = contrastive_arrays(dev, "validation")
    result = []
    for name in CONFIGS:
        w = ablation_weights(name, X)
        folds = []
        for drummer, held, component in performer_folds(dev):
            fw = ablation_weights(name, X[~held])
            selected = [t for t, keep in zip(trips, held) if keep]
            keys = [component[t["anchor"]] for t in selected]
            scores = correct(X[held] @ fw)
            folds.append({"drummer": drummer, "triplets": len(scores), "components": len(set(keys)),
                          "accuracy": float(scores.mean()), "component_macro_accuracy": cluster_score(scores, keys),
                          "top10_mass": float(np.sort(fw)[-10:].sum()),
                          "top10_overlap_full_fit": len(set(np.argsort(-fw)[:10]) & set(np.argsort(-w)[:10]))})
        result.append({"name": name, "status": "EXPLORATORY", "train_accuracy": float(correct(X @ w).mean()),
                       "validation_accuracy": float(correct(V @ w).mean()), "top10_mass": float(np.sort(w)[-10:].sum()),
                       "flux_mass": float(w[:64].sum()), "cv_performer_macro": float(np.mean([f["accuracy"] for f in folds])),
                       "cv_performer_component_macro": float(np.mean([f["component_macro_accuracy"] for f in folds])),
                       "folds": folds})
    return result


def gradient_check(theta, X, reg, epsilon=1e-6):
    offset = np.zeros(len(X))
    loss, analytic = contrastive_objective(theta, X, offset, reg)
    numeric = []
    for i in range(len(theta)):
        delta = np.zeros_like(theta)
        delta[i] = epsilon
        numeric.append((contrastive_objective(theta+delta, X, offset, reg)[0] -
                        contrastive_objective(theta-delta, X, offset, reg)[0]) / (2*epsilon))
    error = float(np.max(np.abs(analytic-numeric)))
    require(error < 1e-7, "Finite-difference gradient check failed")
    require(contrastive_objective(theta-1e-3*analytic, X, offset, reg)[0] <= loss + 1e-14,
            "Negative gradient increases objective")
    return error


def row_structure(row):
    target = np.asarray(row["target"]).reshape(9, 16)
    phases = np.flatnonzero(target.sum(axis=0))
    gaps = np.diff(np.r_[phases, phases[0]+16])
    return {"occupied_cells": int(target.sum()), "active_phases": len(phases),
            "ioi_cv": float(gaps.std()/gaps.mean()),
            "offbeat_fraction": float(target[:, np.arange(16) % 4 != 0].sum()/target.sum())}


def analyze(dev, learned):
    X, _ = contrastive_arrays(dev, "train")
    trace = []
    reproduced, _ = fit_head(X, np.zeros(len(X)), trace=trace)
    require(np.max(np.abs(reproduced-learned)) < 1e-12, "Original optimizer no longer reproduces saved weights")
    theta = trace[-1]
    lookup = {r["id"]: r for r in dev["rows"]}
    component = components(dev["rows"], dev["triplets"])
    per_triplet, per_original, groups, splits = [], [], [], {}
    for split in ("train", "validation"):
        rows = [r for r in dev["rows"] if r["split"] == split]
        x, trips = contrastive_arrays(dev, split)
        baseline, saved = x.mean(axis=1), x @ learned
        b, l = correct(baseline), correct(saved)
        structures = {r["id"]: row_structure(r) for r in rows}
        phase_scores = []
        for r in rows:
            audio = np.asarray(r["features"][:64]).reshape(4, 16).sum(axis=0)
            target = np.asarray(r["target"]).reshape(9, 16).sum(axis=0)
            a, t = audio-audio.mean(), target-target.mean()
            norm = np.linalg.norm(a)*np.linalg.norm(t)
            correlations = [float(a @ np.roll(t, s)/norm) if norm > 1e-10 else 0. for s in range(16)]
            phase_scores.append((correlations[0], max(correlations), int(np.argmax(correlations))))
        for i, triplet in enumerate(trips):
            a, p, n = (lookup[triplet[k]] for k in ROLES)
            dp, dn = (annotation_distance(a["target"], r["target"]) for r in (p, n))
            record = {**triplet, "drummer": a["drummer"], "bpm": a["bpm"], "component": component[a["id"]],
                      "baseline_correct": float(b[i]), "learned_correct": float(l[i]),
                      "baseline_dpos_minus_dneg": float(baseline[i]), "learned_dpos_minus_dneg": float(saved[i]),
                      "midi_positive_distance": dp, "midi_negative_distance": dn,
                      **{f"anchor_phase_{j}_present": int(np.asarray(a["target"]).reshape(9, 16)[:, j].sum() > 0) for j in range(16)},
                      **{"anchor_"+k: v for k, v in structures[a["id"]].items()}}
            per_triplet.append(record)
        current = per_triplet[-len(trips):]
        selectors = {"drummer": lambda t: t["drummer"], "bpm": lambda t: str(t["bpm"]),
                     "component": lambda t: t["component"],
                     "density": lambda t: "<16" if t["anchor_occupied_cells"] < 16 else "16..31" if t["anchor_occupied_cells"] < 32 else ">=32",
                     "regularity": lambda t: "IOI-CV<0.5" if t["anchor_ioi_cv"] < .5 else "IOI-CV>=0.5",
                     "offbeat": lambda t: "<0.5" if t["anchor_offbeat_fraction"] < .5 else ">=0.5",
                     "midi_margin": lambda t: "<0.3" if t["midi_margin"] < .3 else "0.3..0.5" if t["midi_margin"] < .5 else ">=0.5"}
        selectors.update({f"phase_{j}": lambda t, j=j: str(t[f"anchor_phase_{j}_present"]) for j in range(16)})
        for axis, key in selectors.items():
            for value in sorted({key(t) for t in current}):
                mask = np.array([key(t) == value for t in current])
                groups.append({"split": split, "axis": axis, "value": value, "triplets": int(mask.sum()),
                               "baseline_accuracy": float(b[mask].mean()), "learned_accuracy": float(l[mask].mean()),
                               "regressions": int(((b > l) & mask).sum()), "recoveries": int(((l > b) & mask).sum())})
        for oid in sorted({r["original_id"] for r in rows}):
            mask = np.array([any(lookup[t[k]]["original_id"] == oid for k in ROLES) for t in trips])
            per_original.append({"split": split, "original_id": oid, "triplets_touching": int(mask.sum()),
                                 "baseline_accuracy": float(b[mask].mean()) if mask.any() else None,
                                 "learned_accuracy": float(l[mask].mean()) if mask.any() else None,
                                 "regressions": int(((b > l) & mask).sum()), "recoveries": int(((l > b) & mask).sum())})
        f = np.asarray([r["features"] for r in rows])
        # Quantify top-four margin selection bias against all eligible MIDI comparisons; no DSP labels.
        pool = defaultdict(list)
        for r in rows:
            pool[r["drummer"], r["bpm"]].append(r)
        eligible = []
        for group in pool.values():
            for a in group:
                candidates = [r for r in group if r["original_id"] != a["original_id"]]
                ds = {r["id"]: annotation_distance(a["target"], r["target"]) for r in candidates}
                eligible.extend(ds[n["id"]]-ds[p["id"]] for p in candidates for n in candidates
                                if p["original_id"] != n["original_id"] and ds[n["id"]]-ds[p["id"]] >= .15)
        splits[split] = {"bars": len(rows), "triplets": len(trips), "components": len({component[t["anchor"]] for t in trips}),
                         "baseline_accuracy": float(b.mean()), "learned_accuracy": float(l.mean()),
                         "baseline_data_loss": float(np.logaddexp(0, (baseline+.05)/.1).mean()),
                         "learned_data_loss": float(np.logaddexp(0, (saved+.05)/.1).mean()),
                         "regressions": int((b > l).sum()), "recoveries": int((l > b).sum()),
                         "selected_midi_margin": describe([t["midi_margin"] for t in trips]), "eligible_midi_margin": describe(eligible),
                         "structure": {k: describe([s[k] for s in structures.values()]) for k in next(iter(structures.values()))},
                         "flux_band_l2": describe(np.linalg.norm(f[:, :64].reshape(-1, 4, 16), axis=2).ravel()),
                         "ac_block_l2": describe(np.linalg.norm(f[:, 64:], axis=1)),
                         "absolute_margin_flux_share_uniform": float(np.abs(x[:, :64]).sum()/np.abs(x).sum()),
                         "absolute_margin_flux_share_learned": float(np.abs(x[:, :64]*learned[:64]).sum()/np.abs(x*learned).sum()),
                         "zero_shift_correlation": describe([r[0] for r in phase_scores]),
                         "best_shift_correlation": describe([r[1] for r in phase_scores]),
                         "best_shift_counts": dict(sorted(Counter(str(r[2]) for r in phase_scores).items()))}
    coordinate_rows = []
    for i in np.argsort(-learned, kind="stable"):
        coordinate = {"index": int(i), "block": "spectral_flux" if i < 64 else "autocorrelation",
                      "band_hz": ((0, 200), (200, 800), (800, 3000), (3000, 8001))[i//16] if i < 64 else None,
                      "phase_or_lag_beats": float((i % 16)/4 if i < 64 else (i-63)/16),
                      "weight": float(learned[i]), "logit": float(theta[i])}
        for split in ("train", "validation"):
            x, _ = contrastive_arrays(dev, split)
            regressions = correct(x.mean(axis=1)) > correct(x @ learned)
            coordinate[split+"_regression_mean_reweighting_contribution"] = float((x[regressions, i]*(learned[i]-1/128)).mean())
            coordinate[split+"_feature_variance"] = float(np.var([r["features"][i] for r in dev["rows"] if r["split"] == split]))
            coordinate[split+"_mean_margin_contribution"] = float((x[:, i]*learned[i]).mean())
            coordinate[split+"_mean_abs_margin_contribution"] = float(np.abs(x[:, i]*learned[i]).mean())
        coordinate_rows.append(coordinate)
    objective, gradient = contrastive_objective(theta, X, np.zeros(len(X)), .01)
    return {"splits": splits, "weights": {"top10_mass": float(np.sort(learned)[-10:].sum()),
            "flux_mass": float(learned[:64].sum()), "ac_mass": float(learned[64:].sum()),
            "effective_coordinates_inverse_simpson": float(1/(learned @ learned)),
            "clipped_upper": int((theta == 2).sum()), "clipped_lower": int((theta == -2).sum()),
            "outward_gradient_at_bound": int((((theta == 2) & (gradient < 0)) | ((theta == -2) & (gradient > 0))).sum()),
            "data_loss": float(objective-.01*np.mean(theta**2)), "regularizer": float(.01*np.mean(theta**2)),
            "max_saved_weight_reproduction_error": float(np.max(np.abs(reproduced-learned)))},
            "gradient_max_abs_errors": {"zero": gradient_check(np.zeros(128), X, .01),
                "interior": gradient_check(np.linspace(-1, 1, 128), X, .1),
                "saved_preprojection_objective": gradient_check(theta, X, .01)}}, per_triplet, per_original, groups, coordinate_rows


def boundary_probe():
    # Controlled numerical probe only; never contributes training examples or acoustic quality metrics.
    results = []
    for sample in (0, 64, 128, 8000):
        audio = np.zeros(32000)
        audio[sample] = 1.
        f = np.asarray(rhythm_features(audio, 16000, 120))
        results.append({"impulse_sample": sample, "flux_l2": float(np.linalg.norm(f[:64])),
                        "ac_l2": float(np.linalg.norm(f[64:]))})
    return {"kind": "CONTROLLED NUMERICAL PROBE - NOT TRAINING", "results": results,
            "finding": "v1 suppresses a transient already present in the first STFT frame (prepend=first frame)",
            "real_error_attribution": "UNRESOLVED; correcting extraction needs a new feature version and re-extraction"}


def write_csv(path, rows):
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=Path("validation/groove-cpu-v1/artifacts.zip"))
    parser.add_argument("--midi-archive", type=Path, help="Optional previously acquired local archive; no network")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.monotonic(), time.process_time()
    dev, weights, integrity, originals, sources = load_archive(args.artifact)
    verify_historical_code(Path(__file__).resolve().parents[3], integrity["training_code_sha256"])
    integrity["historical_code_identity"] = "PASS"
    integrity["midi_target_reconstruction"] = verify_midi(args.midi_archive, dev, originals, sources) if args.midi_archive else {"status": "NOT RUN: local MIDI archive not supplied"}
    analysis, triplets, originals, groups, coordinates = analyze(dev, weights)
    experiments = ablations(dev)
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "summary.json", {"status": "EXPLORATORY - NOT A VALIDATED MODEL", "integrity": integrity,
              "analysis": analysis, "ablations": experiments, "boundary_probe": boundary_probe(),
              "diagnostic_code_sha256": file_hash(__file__), "optimizer_code_sha256": file_hash(Path(__file__).with_name("model.py")),
              "resources": {"wall_seconds": time.monotonic()-started, "cpu_seconds": time.process_time()-cpu,
                            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                            "dataset_download_bytes": 0, "remote_training_jobs": 0, "gpu": False}})
    for name, rows in (("triplets", triplets), ("originals", originals), ("groups", groups), ("coordinates", coordinates)):
        write_csv(args.output / (name+".csv"), rows)
    print(json.dumps({"output": str(args.output), "status": "EXPLORATORY", "ablations": len(experiments)}))


if __name__ == "__main__":
    main()
