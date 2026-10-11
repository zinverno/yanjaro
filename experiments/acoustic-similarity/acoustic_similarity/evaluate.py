"""Artist-clustered held-out comparisons; absent labels are NOT RUN, never zero."""
import numpy as np

from .data import ASPECTS, CASES, SCHEMA, artist_clusters, digest, require, validate_labels, validate_manifest
from .model import distances, validate_model, vectors


def summary(observations):
    if not observations:
        return {"status": "NOT RUN", "n": 0, "reason": "No reviewed acoustic triplets"}
    groups = {}
    for group, baseline, learned in observations:
        groups.setdefault(group, []).append((baseline, learned))
    # Equal artist-group weight; multiple judgements are not independent samples.
    values = np.array([np.mean(v, axis=0) for v in groups.values()])
    result = {"status": "PASS", "n": len(observations), "artist_groups": len(groups),
              "baseline_accuracy": float(values[:, 0].mean())}
    if np.isfinite(values[:, 1]).all():
        delta = values[:, 1] - values[:, 0]
        result.update(learned_accuracy=float(values[:, 1].mean()), delta=float(delta.mean()))
        if len(groups) >= 5:
            rng = np.random.default_rng(20261011)
            boots = [rng.choice(delta, size=len(delta), replace=True).mean() for _ in range(2000)]
            result["paired_delta_ci95"] = np.quantile(boots, [.025, .975]).tolist()
        else:
            result["paired_delta_ci95"] = None
    return result


def evaluate(manifest, index, labels, cache=None, model=None, *, split="test", allow_synthetic=False):
    require(split in ("validation", "test"), "Evaluate on validation or test only")
    tracks = validate_manifest(manifest)
    triplets = validate_labels(labels, manifest)
    selected = [t for t in triplets if tracks[t["anchor"]]["split"] == split]
    # Shared candidates also correlate judgements, even with different anchors.
    clusters = artist_clusters({str(i): {"artist_ids": sorted({a for key in ("anchor", "positive", "negative")
                                                              for a in tracks[t[key]]["artist_ids"]})}
                                for i, t in enumerate(selected)})
    bank, rows = vectors(index, manifest, cache)
    weights = validate_model(model, bank, cache, allow_synthetic=allow_synthetic) if model else None
    if model:
        require(model["dataset_sha256"] == digest(manifest) and model["labels_sha256"] == digest(labels) and
                model["index_sha256"] == digest(index) and model["embeddings_sha256"] == digest(cache),
                "Evaluation inputs differ from frozen training provenance")
        eval_tracks = [t for t in tracks.values() if t["split"] == split]
        require(not ({a for t in eval_tracks for a in t["artist_ids"]} & set(model["training_artist_ids"])) and
                not ({t["recording_group"] for t in eval_tracks} & set(model["training_recording_groups"])),
                "Model saw evaluation artists/recordings")
    observations = {k: [] for k in ASPECTS}
    cases = {case: {k: [] for k in ASPECTS} for case in CASES}
    def credit(delta):
        return 1. if delta > 1e-10 else .5 if abs(delta) <= 1e-10 else 0.
    for i, t in enumerate(selected):
        a, p, n = (t[k] for k in ("anchor", "positive", "negative"))
        k = t["aspect"]
        base = credit(distances(a, n, rows, bank)[k] - distances(a, p, rows, bank)[k])
        learned = credit(distances(a, n, rows, bank, weights)[k] - distances(a, p, rows, bank, weights)[k]) if weights else np.nan
        observation = (clusters[str(i)], base, learned)
        observations[k].append(observation)
        for case in t["cases"]:
            cases[case][k].append(observation)
    metrics = {k: summary(v) for k, v in observations.items()}
    slices = {c: {k: summary(v) for k, v in aspects.items()} for c, aspects in cases.items()}
    # Preregistered evidence floors, not a statistical power guarantee.
    required_slices = [slices[CASES[0]]["rhythm"], slices[CASES[1]]["rhythm"], slices[CASES[2]]["timbre"]]
    enough = all(m.get("n", 0) >= 50 and m.get("artist_groups", 0) >= 5 for m in metrics.values())
    enough &= all(m.get("n", 0) >= 20 and m.get("artist_groups", 0) >= 5 for m in required_slices)
    improvements = all(m.get("paired_delta_ci95") and m["paired_delta_ci95"][0] > 0 for m in metrics.values())
    slice_safe = all(m.get("paired_delta_ci95") and m["paired_delta_ci95"][0] >= 0 for m in required_slices)
    status = "NOT ESTABLISHED"
    if model and manifest["kind"] == "real" and enough and split == "test":
        status = "PASS" if improvements and slice_safe else "FAIL"
    return {"schema": SCHEMA, "kind": manifest["kind"], "split": split,
            "baseline": "dsp+frozen-MERT" if cache else "dsp-only",
            "dataset_sha256": digest(manifest), "labels_sha256": digest(labels),
            "index_sha256": digest(index), "model_sha256": digest(model) if model else None,
            "aspects": metrics, "cases": slices, "improvement": status,
            "tempo_ground_truth": "NOT RUN - requires reviewed BPM annotations",
            "note": "Accuracy is triplet ordering, not catalogue recall or user preference. Ties=0.5."}
