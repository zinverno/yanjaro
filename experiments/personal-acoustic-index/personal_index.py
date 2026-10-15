#!/usr/bin/env python3
"""Local experimental acoustic index. No automatic capture, audio export or network API."""
import argparse
import json
import logging
import os
from pathlib import Path
import resource
import sys

from runtime import configure
configure()
logging.disable(logging.CRITICAL)

from core import Index, Rejected, extract, identity, read_file, require, track_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", type=Path)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--probe", action="store_true", help="Local metadata preflight; never opens a PCM stream")
    mode.add_argument("--query", metavar="ENTRY_ID")
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--delete", metavar="ENTRY_ID")
    mode.add_argument("--delete-all", action="store_true")
    parser.add_argument("--index-dir", type=Path, default=Path.home() / ".local/share/yanjaro-personal-acoustic/v1")
    parser.add_argument("--entry-id", help="Local file label; no Yandex identity inferred")
    parser.add_argument("--track-id", help="Manual numeric ID, verified against Yanjaro's MPRIS hash")
    parser.add_argument("--rights-confirmed", action="store_true", help="Owner confirms rights to analyze the local file")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--replace", action="store_true", help="Explicitly replace an existing observation of this ID")
    args = parser.parse_args()
    if args.probe:
        from live import Mpris, pactl, select_audio
        observer = Mpris()
        try:
            snapshot = observer.snapshot()
            select_audio(observer.pid, pactl("sink-inputs"), pactl("sinks"))
            result = {"status": "LOCAL_METADATA_READY", "capture": "NOT_RUN", "pcm_streams_opened": 0,
                      "mpris": snapshot["status"], "identity": "MANUAL_ID_REQUIRED"}
        finally:
            observer.close()
    else:
        index = Index(args.index_dir)
        if args.file:
            require(args.rights_confirmed and args.entry_id and args.track_id is None, "LOCAL_RIGHTS_AND_ENTRY_ID_REQUIRED")
            pcm, sr = read_file(args.file, args.start, args.seconds)
            record = extract(pcm, sr, args.entry_id, identity(), "file")
            result = {"status": index.put(record, args.replace), "entry_id": args.entry_id, "dimensions": 705}
        elif args.live:
            require(args.track_id is not None and args.entry_id is None, "LIVE_TRACK_ID_REQUIRED")
            track_id(args.track_id)
            from live import capture_owner
            pcm, sr, binding, title, artists, capture = capture_owner(args.track_id)
            record = extract(pcm, sr, "yandex-" + args.track_id, binding, "live", title, artists, capture)
            result = {"status": index.put(record, args.replace), "entry_id": record["profile"]["id"], "dimensions": 705}
        elif args.query:
            result = index.search(args.query, args.top)
        elif args.list:
            result = [{"entry_id": r["profile"]["id"], "title": r["profile"]["title"], "source": r["source"],
                       "observed_at": r["observed_at"], "missing": list(r["profile"]["missing_reasons"])} for r in index.records()]
        else:
            result = {"deleted": index.delete(args.delete), "remaining": len(index.records())}
    print(json.dumps({"result": result, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Rejected as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)}))
        sys.exit(2)
    except KeyboardInterrupt:
        print('{"status":"CANCELLED_NO_VECTOR_SAVED"}')
        sys.exit(2)
    except Exception:
        # Raw exceptions from audio/DBus/libraries may contain private metadata.
        print('{"status":"BLOCKED","reason":"LOCAL_RESOURCE_OR_SERVICE_ERROR","automatic_retry":false}')
        sys.exit(2)
