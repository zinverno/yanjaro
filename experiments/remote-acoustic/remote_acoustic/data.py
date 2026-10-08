"""Bounded, chronological examples from Yambda-50M's explicit feedback.

The data card specifies uid/item_id/timestamp.  Timestamp is a 5-second bucket.
The selected positive and negative track are NEVER used as context, and
context timestamps precede both judgements. This is a proxy for short-term
preferences; it is NOT a validated mood label.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import math
import os
from contextlib import ExitStack
from itertools import islice
from .remote_io import RangeFile, EMBEDDINGS, MIB


def atomic_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for item in rows:
                f.write(json.dumps(item, separators=(",", ":"), allow_nan=False) + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_events(path: Path, kind: str, max_users: int = 0) -> dict[int, list[tuple[int, int, str]]]:
    """Read just needed fields; 50M likes/dislikes files are much smaller than listens."""
    import pyarrow.parquet as pq
    groups: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    pf = pq.ParquetFile(path)
    required = {"uid", "item_id", "timestamp"}
    if not required <= set(pf.schema_arrow.names):
        raise ValueError(f"{kind}: missing columns {required - set(pf.schema_arrow.names)}")
    for batch in pf.iter_batches(batch_size=32768, columns=["uid", "item_id", "timestamp"]):
        d = batch.to_pydict()
        for uid, track, ts in zip(d["uid"], d["item_id"], d["timestamp"]):
            uid, track, ts = int(uid), int(track), int(ts)
            # Yambda-50M has ~10K anonymized users, not a user's real Yandex ID.
            groups[uid].append((ts, track, kind))
    if max_users:
        keep = set(sorted(groups)[:max_users])
        return {k:groups[k] for k in keep}
    return groups


def build_pairs(likes: dict[int, list[tuple[int, int, str]]],
                dislikes: dict[int, list[tuple[int, int, str]]],
                *, window_days: int = 14, context_len: int = 8,
                per_user: int = 64, max_pairs: int = 50_000) -> list[dict]:
    if not (1 <= window_days <= 60 and 2 <= context_len <= 64 and 1 <= per_user <= 1000):
        raise ValueError("Invalid training bounds")
    window = window_days * 86400 // 5
    examples = []
    for uid in sorted(set(likes) & set(dislikes)):
        pos = sorted((ts, tid) for ts, tid, _ in likes[uid])
        neg = sorted((ts, tid) for ts, tid, _ in dislikes[uid])
        if len(pos) < 3 or not neg:
            continue
        pos_times = [x[0] for x in pos]
        seen = set()
        count = 0
        for neg_time, neg_id in neg:
            place = bisect_left(pos_times, neg_time)
            choices = []
            for idx in range(max(0, place-3), min(len(pos), place+4)):
                ts, item = pos[idx]
                if item != neg_id and abs(ts-neg_time) <= window:
                    choices.append((abs(ts-neg_time), ts, item))
            if not choices:
                continue
            _, pos_time, pos_id = min(choices)
            cutoff = min(pos_time, neg_time)
            context = [tid for ts, tid in pos if ts < cutoff and tid not in (pos_id, neg_id)]
            context = list(dict.fromkeys(context[-context_len:]))
            if len(context) < 2:
                continue
            key = (uid, tuple(context), pos_id, neg_id)
            if key in seen:
                continue
            seen.add(key)
            examples.append({"uid": uid, "time": cutoff, "context": context,
                             "positive": pos_id, "negative": neg_id})
            count += 1
            if count >= per_user or len(examples) >= max_pairs:
                break
        if len(examples) >= max_pairs:
            break
    return examples


def required_ids(pairs: list[dict]) -> set[int]:
    return {int(tid) for pair in pairs for tid in (
        list(pair["context"]) + [pair["positive"], pair["negative"]])}


def load_pairs(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        pairs = [json.loads(line) for line in f if line.strip()]
    for p in pairs:
        if not isinstance(p.get("uid"), int) or not isinstance(p.get("context"), list) or \
                not isinstance(p.get("positive"), int) or not isinstance(p.get("negative"), int):
            raise ValueError("Invalid pair data")
    return pairs


def is_holdout(uid: int, fraction: float = 0.20) -> bool:
    """Stable user-disjoint evaluation: no same user in fit and holdout."""
    if not 0 < fraction < 0.5:
        raise ValueError("Invalid holdout fraction")
    n = int.from_bytes(hashlib.sha256(str(uid).encode()).digest()[:8], "big")
    return n / (2**64) < fraction


def download_small_yambda(destination: Path):
    """Never fetches the 13.8 GB embedding file in this step."""
    destination.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in ("likes", "dislikes"):
        p = destination / f"{name}.parquet"
        with RangeFile(f"flat/50m/{name}.parquet", max_bytes=32*MIB,
                       max_seconds=120) as source:
            content = source.read(source.size)
        p.write_bytes(content)
        paths[name] = p
    return paths


def extract_needed_embeddings(source: str, ids: set[int], *, batch_size: int = 4096,
                              max_batches: int = 100, max_read_mib: int = 512,
                              max_seconds: int = 600, report: dict | None = None):
    """Batch count limits decoded rows; byte/time limits bound actual remote reads."""
    import numpy as np
    import pyarrow.parquet as pq
    if max_batches < 0 or not 1 <= max_read_mib <= 8192 or not 1 <= max_seconds <= 3600:
        raise ValueError("Invalid extraction bounds")
    if not ids:
        return {}
    stats = report if report is not None else {}
    with ExitStack() as stack:
        if source.startswith("hf://"):
            if source != EMBEDDINGS:
                raise ValueError("Use the pinned Yambda embedding source")
            handle = stack.enter_context(RangeFile("embeddings.parquet",
                         max_bytes=max_read_mib*MIB, max_seconds=max_seconds))
        else:
            handle = source
        pf = stack.enter_context(pq.ParquetFile(handle, pre_buffer=False))
        embeddings = {}
        try:
            if not {"item_id", "normalized_embed"} <= set(pf.schema_arrow.names):
                raise ValueError("Yambda embeddings.parquet must contain item_id, normalized_embed")
            batches = pf.iter_batches(batch_size=batch_size,
                                      columns=["item_id", "normalized_embed"], use_threads=False)
            # islice stops BEFORE asking Arrow for an extra batch/row group.
            if max_batches:
                batches = islice(batches, max_batches)
            rows = 0
            for batch in batches:
                rows += batch.num_rows
                for tid, vec in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist()):
                    tid = int(tid)
                    if tid not in ids or tid in embeddings:
                        continue
                    if not isinstance(vec, (list, tuple)) or not vec or not all(
                            isinstance(x, (float, int)) and math.isfinite(float(x)) for x in vec):
                        raise ValueError("Invalid required audio embedding")
                    embeddings[tid] = np.asarray(vec, dtype=np.float32)
                if len(embeddings) == len(ids):
                    break
            stats.update(rows_read=rows, dataset_rows=pf.metadata.num_rows,
                         complete_scan=rows == pf.metadata.num_rows,
                         wanted_ids=len(ids), found_ids=len(embeddings),
                         max_batches=max_batches)
            return embeddings
        finally:
            if isinstance(handle, RangeFile):
                stats.update(handle.stats())


def save_vectors(path: Path, vectors: dict[int, list[float]]):
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    if not vectors:
        raise ValueError("No real audio embeddings matched")
    sorted_ids = sorted(vectors)
    d = len(vectors[sorted_ids[0]])
    if d < 8 or any(len(vectors[k]) != d for k in sorted_ids):
        raise ValueError("Inconsistent Yambda embedding dimension")
    ids = np.array(sorted_ids, dtype=np.int64)
    matrix = np.asarray([vectors[k] for k in sorted_ids], dtype=np.float32)
    if not np.isfinite(matrix).all():
        raise ValueError("Nonfinite embeddings")
    with path.open("wb") as f:
        np.savez_compressed(f, item_ids=ids, embeddings=matrix)
    return len(sorted_ids), d
