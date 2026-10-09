"""Bounded research pipeline. No implicit full scan or synthetic fallback."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import resource
import shutil
import numpy as np
from .data import (read_events, build_pairs, atomic_jsonl, required_ids, load_pairs,
                   download_small_yambda, extract_needed_embeddings, save_vectors)
from .model import build_training_arrays, train, export_model
from .remote_io import RangeFile, REVISION, EMBEDDINGS, MIB, parquet_layout


def parse_row_groups(value):
    if not re.fullmatch(r'[0-9]+(?:,[0-9]+)*', value):
        raise argparse.ArgumentTypeError('Use comma-separated nonnegative row-group indices')
    groups = [int(i) for i in value.split(',')]
    if len(groups) > 30 or len(set(groups)) != len(groups) or any(i >= 30 for i in groups):
        raise argparse.ArgumentTypeError('Use unique Yambda row groups in 0..29')
    return groups


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def receipt(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')


def probe(output):
    import pyarrow.parquet as pq
    report = {'source': 'yandex/yambda', 'revision': REVISION, 'status': 'FAIL',
              'byte_limit': 128*MIB, 'seconds_limit': 180}
    handle = None
    try:
        handle = RangeFile('embeddings.parquet', max_bytes=128*MIB, max_seconds=180)
        with handle, pq.ParquetFile(handle, pre_buffer=False) as pf:
            report.update(parquet_layout(pf))
            group = min(report['row_groups'], key=lambda g: g['compressed_bytes'])
            batch = next(pf.iter_batches(batch_size=256, row_groups=[group['index']],
                         columns=['item_id', 'normalized_embed'], use_threads=False))
            vectors = np.asarray(batch.column(1).to_pylist())
            if vectors.ndim != 2 or not 8 <= vectors.shape[1] <= 2048 or not np.isfinite(vectors).all():
                raise ValueError('Invalid Yambda embedding sample')
            norms = np.linalg.norm(vectors, axis=1)
            if not np.allclose(norms, 1, atol=1e-5):
                raise ValueError('Yambda normalized vectors are not unit length')
            report.update(status='PASS', sampled_group=group['index'],
                          sample_rows=len(vectors), dimension=vectors.shape[1],
                          sample_norm_min=float(norms.min()), sample_norm_max=float(norms.max()))
    except Exception as e:
        report['error_type'] = type(e).__name__
        raise
    finally:
        if handle:
            report['io'] = handle.stats()
        report['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['disk_free_bytes'] = shutil.disk_usage(output.parent if output.parent.exists() else '.').free
        receipt(output, report)
    print(json.dumps(report, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    inspect = subs.add_parser('probe', help='128 MiB / 180 second range and schema probe')
    inspect.add_argument('--output', type=Path, default=Path('artifacts/probe.json'))
    coverage = subs.add_parser('coverage', help='ID-only coverage plan: 32 MiB / 180 seconds, no vectors')
    coverage.add_argument('--work', type=Path, default=Path('work'))
    coverage.add_argument('--output', type=Path, default=Path('artifacts/coverage.json'))
    prepare = subs.add_parser('prepare', help='Pinned real Yambda-50M feedback')
    prepare.add_argument('--work', type=Path, default=Path('work'))
    prepare.add_argument('--max-users', type=int, default=10_000)
    prepare.add_argument('--days', type=int, default=14)
    extract = subs.add_parser('extract', help='Bounded projected embedding scan')
    extract.add_argument('--work', type=Path, default=Path('work'))
    extract.add_argument('--parquet', default=EMBEDDINGS)
    extract.add_argument('--max-batches', type=int, default=100,
                         help='0 removes the row limit; byte/time limits still apply')
    extract.add_argument('--max-read-mib', type=int, default=512)
    extract.add_argument('--max-seconds', type=int, default=600)
    extract.add_argument('--row-groups', type=parse_row_groups,
                         help='Explicit comma-separated ordinals, e.g. 29; same byte/time limits')
    fit = subs.add_parser('train', help='Fit once, report user-disjoint holdout')
    fit.add_argument('--work', type=Path, default=Path('work'))
    fit.add_argument('--output', type=Path, default=Path('artifacts/model.json'))
    fit.add_argument('--min-covered-pairs', type=int, default=100)
    args = parser.parse_args(argv)
    if args.command == 'probe':
        probe(args.output)
    elif args.command == 'coverage':
        import pyarrow.parquet as pq
        from .coverage import coverage_report
        prep = json.loads((args.work/'prepare.json').read_text())
        if (prep.get('source') != 'yandex/yambda' or prep.get('revision') != REVISION
                or prep.get('pairs_sha256') != digest(args.work/'pairs.jsonl')):
            raise ValueError('Missing or inconsistent real-data provenance')
        # Remove stale diagnostics before a new bounded attempt.
        args.output.unlink(missing_ok=True)
        with RangeFile('embeddings.parquet', max_bytes=32*MIB, max_seconds=180) as source:
            with pq.ParquetFile(source, pre_buffer=False) as pf:
                report = coverage_report(pf, load_pairs(args.work/'pairs.jsonl'))
            report.update(source='yandex/yambda', revision=REVISION, status='PASS', io=source.stats())
        receipt(args.output, report)
        print(json.dumps(report, indent=2))
    elif args.command == 'prepare':
        if not 1 <= args.max_users <= 10_000:
            raise ValueError('max-users must be in 1..10000')
        args.work.mkdir(parents=True, exist_ok=True)
        (args.work/'prepare.json').unlink(missing_ok=True)
        files = download_small_yambda(args.work)
        likes = read_events(files['likes'], 'like', args.max_users)
        dislikes = read_events(files['dislikes'], 'dislike', args.max_users)
        pairs = build_pairs(likes, dislikes, window_days=args.days)
        if len(pairs) < 40:
            raise ValueError(f'Only {len(pairs)} pairs; insufficient')
        atomic_jsonl(args.work/'pairs.jsonl', pairs)
        receipt(args.work/'required_ids.json', sorted(required_ids(pairs)))
        data = {'source': 'yandex/yambda', 'revision': REVISION, 'pairs': len(pairs),
                'unique_ids': len(required_ids(pairs)), 'max_users': args.max_users,
                'window_days': args.days, 'context_len': 8, 'per_user': 64, 'max_pairs': 50000,
                'likes_users': len(likes), 'dislikes_users': len(dislikes),
                'likes_events': sum(map(len, likes.values())),
                'dislikes_events': sum(map(len, dislikes.values())),
                'pairs_sha256': digest(args.work/'pairs.jsonl'),
                'event_sha256': {k: digest(v) for k, v in files.items()}}
        receipt(args.work/'prepare.json', data)
        print(json.dumps(data))
    elif args.command == 'extract':
        (args.work/'extract.json').unlink(missing_ok=True)
        (args.work/'vectors.npz').unlink(missing_ok=True)
        ids = set(json.loads((args.work/'required_ids.json').read_text()))
        report = {'source': 'yandex/yambda' if args.parquet == EMBEDDINGS else 'unverified-local',
                  'revision': REVISION, 'status': 'FAIL'}
        try:
            vectors = extract_needed_embeddings(args.parquet, ids, max_batches=args.max_batches,
                        max_read_mib=args.max_read_mib, max_seconds=args.max_seconds, report=report,
                        row_groups=args.row_groups)
            num, dimension = save_vectors(args.work/'vectors.npz', vectors)
            report.update(status='PASS', found_ids=num, dimension=dimension,
                          vectors_sha256=digest(args.work/'vectors.npz'))
        finally:
            receipt(args.work/'extract.json', report)
        print(json.dumps(report))
    elif args.command == 'train':
        args.output.unlink(missing_ok=True)
        metrics_path = args.output.with_name('metrics.json')
        metrics_path.unlink(missing_ok=True)
        prep = json.loads((args.work/'prepare.json').read_text())
        extraction = json.loads((args.work/'extract.json').read_text())
        if (prep.get('source') != 'yandex/yambda' or extraction.get('source') != 'yandex/yambda'
                or prep.get('revision') != REVISION or extraction.get('revision') != REVISION
                or extraction.get('status') != 'PASS'
                or prep.get('pairs_sha256') != digest(args.work/'pairs.jsonl')
                or extraction.get('vectors_sha256') != digest(args.work/'vectors.npz')):
            raise ValueError('Missing or inconsistent real-data provenance')
        pairs = load_pairs(args.work/'pairs.jsonl')
        with np.load(args.work/'vectors.npz', allow_pickle=False) as f:
            bank = dict(zip(map(int, f['item_ids']), f['embeddings']))
        X, val, coverage = build_training_arrays(pairs, bank)
        if len(X) < max(100, args.min_covered_pairs) or len(X[~val]) < 20 or len(X[val]) < 8:
            raise ValueError(f'Insufficient matched real pairs: {coverage}')
        weights, metrics = train(X, val)
        provenance = {'dataset_revision': REVISION, 'dataset_subset': 'flat/50m',
                      'code_sha': os.environ.get('GITHUB_SHA'),
                      'run_id': os.environ.get('GITHUB_RUN_ID'),
                      'prepare': prep, 'extraction': extraction}
        report = {'source': 'yandex/yambda', **metrics, 'coverage': coverage, 'provenance': provenance,
                  'holdout_improved': metrics['learned_holdout_accuracy'] > metrics['cosine_baseline_holdout_accuracy']}
        export_model(args.output, weights, metrics, source='yandex/yambda', extra={
            'coverage': coverage, 'provenance': provenance,
            'training_note': 'Explicit like/dislike proxy, not mood labels; fixed hyperparameters, no holdout tuning.',
            'yandex_id_mapping': 'unavailable', 'catalog_coverage': 'not established'})
        report['model_sha256'] = digest(args.output)
        receipt(metrics_path, report)
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
