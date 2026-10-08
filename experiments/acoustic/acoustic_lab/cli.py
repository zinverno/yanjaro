"""Simple CLI for a standalone, opt-in acoustic ML experiment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .core import (index_directory,load_library,load_sessions,write_json,new_session,
                   rate,train_ranker,recommend)


def _build_parser():
    parser=argparse.ArgumentParser(prog="yanjaro-acoustic",description="Offline acoustic profiling and session model (no Yandex audio/API)")
    parser.add_argument("--workspace",default=".local",help="Local private output dir; do not commit to Git")
    sub=parser.add_subparsers(dest="command",required=True)
    index=sub.add_parser("index",help="Analyze local audio files without persisting audio")
    index.add_argument("directory",type=Path)
    index.add_argument("--limit",type=int,default=20,help="Max NEW files analyzed on this run (default 20)")
    index.add_argument("--seconds",type=int,default=180,help="Analyze up to first N seconds (10–300)")
    index.add_argument("--max-file-mb",type=int,default=150)
    sub.add_parser("list",help="List indexed IDs, names and estimated BPM")
    new=sub.add_parser("new-session",help="Begin a context using already indexed seed songs")
    new.add_argument("id",help="Session label e.g. late-evening")
    new.add_argument("seeds",nargs="+",help="One or more track IDs from list")
    vote=sub.add_parser("rate",help="Explicit response: fits this session right now or not")
    vote.add_argument("session_id")
    vote.add_argument("track_id")
    vote.add_argument("vote",choices=["yes","no"])
    rec=sub.add_parser("recommend",help="Baseline if model absent, learned weights when trained")
    rec.add_argument("session_id")
    rec.add_argument("--limit",type=int,default=10)
    sub.add_parser("train",help="Train acoustic-distance weights from sessions; save JSON")
    return parser


def main(argv=None):
    parser=_build_parser()
    args=parser.parse_args(argv)
    root=Path(args.workspace).expanduser().resolve()
    library_path=root/"library.json"
    session_path=root/"sessions.json"
    model_path=root/"model.json"
    try:
        if args.command=="index":
            print(json.dumps(index_directory(args.directory,root,args.limit,args.seconds,args.max_file_mb),ensure_ascii=False,indent=2))
            return 0
        lib=load_library(library_path)
        if args.command=="list":
            if not lib["tracks"]:
                print("Library empty: run index first")
            for id,r in sorted(lib["tracks"].items(),key=lambda it:it[1]["name"]):
                print(f"{id}  ~{r['features']['bpm']:.0f} BPM  {r['name']}")
            return 0
        data=load_sessions(session_path)
        if args.command=="new-session":
            new_session(data,args.id,args.seeds,lib)
            write_json(session_path,data)
            print("Created",args.id,"with",len(args.seeds),"seeds")
            return 0
        if args.command=="rate":
            rate(data,args.session_id,args.track_id,args.vote=="yes",lib)
            write_json(session_path,data)
            print("Saved explicit rating:",args.vote)
            return 0
        if args.command=="train":
            trained=train_ranker(lib,data)
            write_json(model_path,trained)
            print(json.dumps(trained["training"],ensure_ascii=False,indent=2))
            print("Learned",len(trained["weights"]),"acoustic feature weights. Model:",model_path)
            return 0
        if args.command=="recommend":
            sess=next((s for s in data["sessions"] if s["id"]==args.session_id),None)
            if not sess:
                raise ValueError("Session not found")
            model=json.loads(model_path.read_text(encoding="utf-8")) if model_path.exists() else None
            print("RANKER:","learned" if model else "rhythm-first baseline, not yet trained")
            for pos,item in enumerate(recommend(lib,sess,model,args.limit),1):
                print(f"{pos:02d}. {item['name']} ~{item['bpm_estimate']} BPM [id={item['id']}, score={item['score']:.3f}]")
            return 0
    except (ValueError,OSError,KeyError,RuntimeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 2
    return 2


if __name__=="__main__":
    raise SystemExit(main())
