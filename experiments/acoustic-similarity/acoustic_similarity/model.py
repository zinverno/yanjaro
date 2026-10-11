"""Three small contrastive diagonal metrics over fixed DSP/frozen audio features."""
import numpy as np

from .data import ASPECTS, SCHEMA, artist_clusters, digest, is_hash, require, validate_labels, validate_manifest
from .features import FEATURE_SCHEMA, code_hash, tempo_distance, validate_index

MODEL_FORMAT = "yanjaro.acoustic.diagonal-heads.v0.1"
ENCODER_ID = "m-a-p/MERT-v1-95M"
POOLING = "last-hidden-state-time-mean-std-5s-chunks-mean-v1"


def validate_embeddings(cache, index):
    require(cache.get("schema") == SCHEMA and cache.get("dataset_sha256") == index["dataset_sha256"],
            "Embedding/dataset mismatch")
    e = cache.get("encoder", {})
    require(e.get("id") == ENCODER_ID and e.get("pooling") == POOLING and e.get("frozen") is True and
            e.get("dimension") == 1536 and is_hash(e.get("snapshot_sha256")) and
            isinstance(e.get("revision"), str) and len(e["revision"]) == 40 and
            all(c in "0123456789abcdef" for c in e["revision"]) and
            e.get("weights_license") == "CC-BY-NC-4.0", "Unidentified/incompatible frozen encoder")
    require(cache.get("kind") == index["kind"], "Synthetic embeddings cannot masquerade as real")
    rows = cache.get("tracks", [])
    require(len(rows) == len(index["tracks"]) and len({t["id"] for t in rows}) == len(rows), "Incomplete embeddings")
    lookup = {t["id"]: t for t in rows}
    for t in index["tracks"]:
        require(t["id"] in lookup and lookup[t["id"]]["sha256"] == t["sha256"], "Embedding/audio mismatch")
        v = np.asarray(lookup[t["id"]]["embedding"], dtype=float)
        with np.errstate(over="ignore", invalid="ignore"):
            norm = np.linalg.norm(v)
        require(v.shape == (1536,) and np.isfinite(v).all() and np.isfinite(norm) and norm > 1e-9,
                "Invalid frozen embedding")
    return lookup


def vectors(index, manifest, cache=None):
    rows = validate_index(index, manifest)
    embeddings = validate_embeddings(cache, index) if cache is not None else None
    result = {}
    for tid, row in rows.items():
        result[tid] = {k: np.asarray(row["vectors"][k], dtype=float) / 3 for k in ASPECTS}
        if embeddings is not None:
            dsp = result[tid]["timbre"]
            emb = np.asarray(embeddings[tid]["embedding"], dtype=float)
            emb = emb / np.linalg.norm(emb)
            n = len(dsp) + len(emb)
            # Equal block influence at initialization despite unequal dimensions.
            result[tid]["timbre"] = np.r_[dsp * np.sqrt(n / (2 * len(dsp))), emb * np.sqrt(n / 2)]
    return result, rows


def softmax(theta):
    values = np.exp(theta - np.max(theta))
    return values / values.sum()


def distances(a, b, rows, bank, weights=None):
    result = {}
    for aspect in ASPECTS:
        diff = (bank[a][aspect] - bank[b][aspect])**2 / 4
        value = float(np.mean(diff) if weights is None else diff @ np.asarray(weights[aspect]))
        if aspect == "rhythm":
            value = .75 * value + .25 * tempo_distance(rows[a]["bpm"], rows[b]["bpm"])
        result[aspect] = value
    result["overall"] = sum(result.values()) / 3
    return result


def contrastive_objective(theta, X, offset, regularization):
    """Total objective and its logit gradient, before the optimizer's projection."""
    weights = softmax(theta)
    z = (X @ weights + offset + .05) / .1
    sigmoid = np.exp(-np.logaddexp(0, -z))
    gw = X.T @ sigmoid / (len(X) * .1)
    gradient = weights * (gw - weights @ gw) + 2 * regularization * theta / len(theta)
    loss = np.mean(np.logaddexp(0, z)) + regularization * np.mean(theta**2)
    return float(loss), gradient


def fit_head(X, offset, *, epochs=300, lr=.1, regularization=.01, logit_bound=2., trace=None):
    """Softplus(margin + d_positive - d_negative); no preference targets."""
    X, offset = np.asarray(X, dtype=float), np.asarray(offset, dtype=float)
    require(X.ndim == 2 and len(X) > 0 and X.shape[1] > 0 and offset.shape == (len(X),) and
            np.isfinite(X).all() and np.isfinite(offset).all(), "Invalid contrastive arrays")
    require(type(epochs) is int and epochs > 0 and np.isfinite([lr, regularization, logit_bound]).all()
            and lr > 0 and regularization >= 0 and logit_bound > 0, "Invalid optimizer settings")
    theta = np.zeros(X.shape[1])
    m, v = np.zeros_like(theta), np.zeros_like(theta)
    for step in range(1, epochs + 1):
        _, g = contrastive_objective(theta, X, offset, regularization)
        m = .9 * m + .1 * g
        v = .999 * v + .001 * g**2
        theta -= lr * (m / (1 - .9**step)) / (np.sqrt(v / (1 - .999**step)) + 1e-8)
        theta = np.clip(theta, -logit_bound, logit_bound)
        if trace is not None:
            trace.append(theta.copy())
    weights = softmax(theta)
    loss = np.mean(np.logaddexp(0, (X @ weights + offset + .05) / .1))
    require(np.isfinite(weights).all() and np.isfinite(loss), "Training diverged")
    return weights.tolist(), float(loss)


def train(manifest, index, labels, cache, *, allow_synthetic=False):
    synthetic = manifest.get("kind") == "synthetic-test-only"
    require(not synthetic or allow_synthetic, "Synthetic training requires explicit test-only mode")
    tracks = validate_manifest(manifest, purpose="training")
    triplets = validate_labels(labels, manifest)
    require(cache is not None, "Training requires a frozen encoder cache")
    bank, rows = vectors(index, manifest, cache)
    selected = [t for t in triplets if tracks[t["anchor"]]["split"] == "train"]
    used_ids = {t[k] for t in selected for k in ("anchor", "positive", "negative")}
    used_artists = {a for tid in used_ids for a in tracks[tid]["artist_ids"]}
    clusters = artist_clusters(tracks)
    artist_count = len({clusters[i] for i in used_ids})
    if not synthetic:
        require(len(used_ids) >= 100 and artist_count >= 20,
                "NOT RUN: need >=100 labelled train recordings and >=20 artist groups")
        for split in ("validation", "test"):
            held_out = {i for i, t in tracks.items() if t["split"] == split}
            require(len(held_out) >= 20 and len({clusters[i] for i in held_out}) >= 5,
                    "NOT RUN: reserve >=20 recordings and >=5 artist groups for " + split)
            require(all(sum(t["aspect"] == k and t["anchor"] in held_out for t in triplets) >= 50
                        for k in ASPECTS), "NOT RUN: need >=50 reviewed triplets per aspect for " + split)
    weights, losses = {}, {}
    for aspect in ASPECTS:
        examples = [t for t in selected if t["aspect"] == aspect]
        require(len(examples) >= (1 if synthetic else 100), "Insufficient training triplets: " + aspect)
        X, offsets = [], []
        for t in examples:
            a, p, n = (t[k] for k in ("anchor", "positive", "negative"))
            row = ((bank[a][aspect] - bank[p][aspect])**2 -
                   (bank[a][aspect] - bank[n][aspect])**2) / 4
            offset = 0.
            if aspect == "rhythm":
                row *= .75
                offset = .25 * (tempo_distance(rows[a]["bpm"], rows[p]["bpm"]) -
                               tempo_distance(rows[a]["bpm"], rows[n]["bpm"]))
            X.append(row)
            offsets.append(offset)
        weights[aspect], losses[aspect] = fit_head(X, offsets)
    return {"schema": SCHEMA, "format": MODEL_FORMAT, "version": "0.1.0",
            "feature_schema": FEATURE_SCHEMA, "kind": manifest["kind"],
            "status": "SYNTHETIC TEST ONLY" if synthetic else "RESEARCH CANDIDATE - NOT VALIDATED",
            "weights": weights, "encoder": cache["encoder"], "dataset_sha256": digest(manifest),
            "labels_sha256": digest(labels), "index_sha256": digest(index), "embeddings_sha256": digest(cache),
            "training_code_sha256": code_hash(), "train_loss": losses,
            "training": {"epochs": 300, "lr": .1, "regularization": .01, "margin": .05,
                         "temperature": .1, "initialization": "zero logits; deterministic full batch Adam",
                         "recordings": len(used_ids), "artist_groups": artist_count,
                         "triplets": {k: sum(t["aspect"] == k for t in selected) for k in ASPECTS}},
            "training_recording_groups": sorted({tracks[i]["recording_group"] for i in used_ids}),
            "training_artist_ids": sorted(used_artists),
            "metrics": {"test": "NOT RUN", "improvement": "NOT ESTABLISHED"}}


def validate_model(model, bank, cache, *, allow_synthetic=False):
    require(model.get("schema") == SCHEMA and model.get("format") == MODEL_FORMAT and
            model.get("feature_schema") == FEATURE_SCHEMA, "Incompatible model")
    require(model.get("kind") == "real" or (allow_synthetic and model.get("kind") == "synthetic-test-only"),
            "Demo/unidentified model rejected")
    require(cache is not None and model.get("encoder") == cache["encoder"], "Model/encoder mismatch")
    require(model["kind"] == cache["kind"], "Model/data kind mismatch")
    example = next(iter(bank.values()))
    for k in ASPECTS:
        w = np.asarray(model["weights"][k], dtype=float)
        require(w.shape == example[k].shape and np.isfinite(w).all() and (w > 0).all() and
                abs(float(w.sum()) - 1) < 1e-8, "Malformed model weights")
    return model["weights"]
