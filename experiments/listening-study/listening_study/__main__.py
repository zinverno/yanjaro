import argparse
import sys
from pathlib import Path
from .common import read_json, write_new


def main():
    parser = argparse.ArgumentParser(description="Yanjaro Listening Study v0.1 — offline research only")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("demo", help="Generate synthetic audio, frozen tasks and scripted responses")
    p.add_argument("out", type=Path)
    p = sub.add_parser("import-mtg", help="Read an explicit <=60-ID subset of a local TSV; no downloading")
    p.add_argument("tsv", type=Path); p.add_argument("out", type=Path)
    p.add_argument("--ids", nargs="+", required=True); p.add_argument("--revision", required=True)
    p = sub.add_parser("prepare", help="Check permissions and extract local audio features")
    p.add_argument("sample", type=Path); p.add_argument("out", type=Path)
    p = sub.add_parser("screen", help="Generate provisional pairs and manual review template")
    p.add_argument("catalog", type=Path); p.add_argument("out", type=Path)
    p = sub.add_parser("freeze", help="Validate approved pairs and freeze an immutable study manifest")
    p.add_argument("catalog", type=Path); p.add_argument("review", type=Path); p.add_argument("out", type=Path)
    p.add_argument("--study-id", required=True); p.add_argument("--seed", type=int, required=True)
    p.add_argument("--phase", choices=("pilot", "confirmatory"), required=True)
    p = sub.add_parser("serve", help="Read-only loopback UI; answers stay in browser memory")
    p.add_argument("study", type=Path); p.add_argument("--slot", type=int, required=True)
    p.add_argument("--question", choices=("next", "similarity"), required=True)
    p.add_argument("--port", type=int, default=8765)
    for command in ("collect", "analyze-collected", "purge-collected"):
        p = sub.add_parser(command, help="Private SQLite collection; loopback preview and operator-only maintenance")
        p.add_argument("study", type=Path); p.add_argument("database", type=Path); p.add_argument("config", type=Path)
        if command == "collect":
            p.add_argument("--port", type=int, default=8765)
        if command == "analyze-collected":
            p.add_argument("out", type=Path)
    p = sub.add_parser("analyze", help="Validate anonymous exports and compute clustered intervals")
    p.add_argument("study", type=Path); p.add_argument("responses", type=Path); p.add_argument("out", type=Path)
    p.add_argument("--draws", type=int, default=2000); p.add_argument("--seed", type=int, default=20261009)
    args = parser.parse_args()
    try:
        if args.command == "demo":
            from .demo import build_demo
            build_demo(args.out)
        elif args.command == "import-mtg":
            from .metadata import import_mtg
            write_new(args.out, import_mtg(args.tsv, args.ids, args.revision))
        elif args.command == "prepare":
            from .audio import prepare
            prepare(read_json(args.sample), args.out)
        elif args.command == "screen":
            from .design import screen
            write_new(args.out, screen(read_json(args.catalog)))
        elif args.command == "freeze":
            from .design import freeze
            write_new(args.out, freeze(read_json(args.catalog), read_json(args.review),
                                       study_id=args.study_id, seed=args.seed, phase=args.phase))
        elif args.command == "serve":
            from .server import make_server
            server = make_server(read_json(args.study), args.slot, args.question, args.port)
            print(f"Local only: http://127.0.0.1:{server.server_port} · slot={args.slot} · {args.question}", flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        elif args.command in ("collect", "analyze-collected", "purge-collected"):
            from .collection import Collection
            collector = Collection(read_json(args.study), args.database, read_json(args.config))
            if args.command == "collect":
                from .server import make_server
                collector.purge()
                server = make_server(collector.study, port=args.port, collection=collector)
                print(f"Collection preview, loopback only: http://127.0.0.1:{server.server_port}", flush=True)
                try:
                    server.serve_forever()
                finally:
                    server.server_close()
            elif args.command == "analyze-collected":
                write_new(args.out, collector.report())
            else:
                collector.purge()
        elif args.command == "analyze":
            from .analysis import analyze
            paths = sorted(args.responses.glob("*.json"))
            if not paths or len(paths) > 10000:
                raise ValueError("Need 1..10000 explicitly collected response files")
            write_new(args.out, analyze(read_json(args.study), [read_json(p) for p in paths], draws=args.draws, seed=args.seed))
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(f"Study error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
