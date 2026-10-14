"""Local research commands. Every output is explicit and create-only."""
import argparse
import json
from pathlib import Path
import sys

from .data import SCHEMA, file_hash, read_json, require, validate_manifest, write_new
from .evaluate import evaluate
from .features import build_index
from .model import distances, train, validate_model, vectors


def search(query, manifest, index, cache=None, model=None, *, top=10,
           query_manifest=None, query_cache=None):
    require(1 <= top <= 100, "top must be 1..100")
    tracks = validate_manifest(manifest, verify_files=True)
    bank, rows = vectors(index, manifest, cache)
    weights = validate_model(model, bank, cache) if model else None
    query_hash = file_hash(query)
    matches = [t for t in rows.values() if t["sha256"] == query_hash]
    if matches:
        query_id = matches[0]["id"]
    else:
        require(query_manifest is not None and len(query_manifest.get("tracks", [])) == 1,
                "New query requires a one-record --query-manifest with reviewed rights")
        q = query_manifest["tracks"][0]
        require(Path(q["path"]).resolve() == Path(query).resolve() and q["sha256"] == query_hash,
                "Query manifest does not describe this file")
        require((cache is None) == (query_cache is None), "Frozen baseline/model requires remote query embeddings")
        if cache is not None:
            require(query_cache["encoder"] == cache["encoder"], "Query encoder mismatch")
        q_index = build_index(query_manifest)
        q_bank, q_rows = vectors(q_index, query_manifest, query_cache)
        query_id = "query:" + query_hash
        require(query_id not in rows, "Query ID collision")
        rows[query_id], bank[query_id] = q_rows[q["id"]], q_bank[q["id"]]
    results = []
    for tid, t in tracks.items():
        if t["sha256"] == query_hash:
            continue
        components = distances(query_id, tid, rows, bank, weights)
        results.append({"id": tid, "path": t["path"], "distance": components.pop("overall"),
                        "components": components, "bpm": rows[tid]["bpm"]})
    results.sort(key=lambda t: (t["distance"], t["id"]))
    return {"schema": SCHEMA, "method": "learned-research-candidate" if model else
            "baseline-dsp+frozen-MERT" if cache else "baseline-dsp",
            "query_sha256": query_hash, "quality": "UNVALIDATED", "results": results[:top]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Acoustic similarity research; no preference learning or downloads")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("index", "search", "train", "evaluate", "embed"):
        p = sub.add_parser(command)
        p.add_argument("--manifest", required=True, type=Path)
        if command not in ("index", "embed"):
            p.add_argument("--index", required=True, type=Path)
            p.add_argument("--embeddings", type=Path)
        if command != "search":
            p.add_argument("--out", required=True, type=Path)
        if command in ("train", "evaluate"):
            p.add_argument("--labels", required=True, type=Path)
        if command == "train":
            p.add_argument("--remote-worker", action="store_true")
        if command in ("search", "evaluate"):
            p.add_argument("--model", type=Path)
        if command == "search":
            p.add_argument("audio", type=Path)
            p.add_argument("--top", type=int, default=10)
            p.add_argument("--query-manifest", type=Path)
            p.add_argument("--query-embeddings", type=Path)
        if command == "evaluate":
            p.add_argument("--split", choices=("validation", "test"), default="test")
        if command == "embed":
            p.add_argument("--snapshot", required=True, type=Path)
            p.add_argument("--receipt", required=True, type=Path)
            p.add_argument("--remote-worker", action="store_true")
            p.add_argument("--trust-reviewed-code", action="store_true")
    args = parser.parse_args(argv)
    def load(name):
        path = getattr(args, name, None)
        return read_json(path) if path else None
    try:
        manifest = load("manifest")
        if args.command == "index":
            result = build_index(manifest)
        elif args.command == "search":
            result = search(args.audio, manifest, load("index"), load("embeddings"), load("model"),
                            top=args.top, query_manifest=load("query_manifest"), query_cache=load("query_embeddings"))
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0
        elif args.command == "train":
            require(args.remote_worker, "Real training belongs on an explicitly selected remote worker")
            validate_manifest(manifest, purpose="remote")
            result = train(manifest, load("index"), load("labels"), load("embeddings"))
        elif args.command == "evaluate":
            result = evaluate(manifest, load("index"), load("labels"), load("embeddings"),
                              load("model"), split=args.split)
        else:
            from .remote import extract_embeddings
            result = extract_embeddings(manifest, args.snapshot, load("receipt"),
                                        authorized_remote=args.remote_worker,
                                        trust_reviewed_code=args.trust_reviewed_code)
        write_new(args.out, result)
        print(json.dumps({"status": "PASS", "output": str(args.out)}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
