"""Reject an unreviewable full scan before requesting its data."""
import argparse
import json
from pathlib import Path
import shutil


def check(report, mode, max_read_mib):
    if report.get('status') != 'PASS':
        raise ValueError('A successful fresh real-data probe is required')
    if max_read_mib not in (512, 1024, 4096, 8192):
        raise ValueError('Invalid byte budget')
    if mode not in ('train-bounded', 'train-full'):
        raise ValueError('Invalid training mode')
    if mode == 'train-full':
        # Small-range timing is only an estimate. Allow 50% headroom.
        projected = report['projected_full_scan_bytes'] + 1024**2
        seconds = projected / report['io']['received_bytes'] * report['io']['seconds'] * 1.5
        if projected > max_read_mib*1024**2 or seconds > 3600:
            raise ValueError(f'Full scan exceeds budget: {projected} bytes, estimated {seconds:.0f}s with headroom')
        return seconds
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', required=True)
    parser.add_argument('--max-read-mib', type=int, required=True)
    args = parser.parse_args()
    report = json.loads(Path('artifacts/probe.json').read_text())
    estimate = check(report, args.mode, args.max_read_mib)
    if shutil.disk_usage('.').free < 1024**3:
        raise SystemExit('Need at least 1 GiB free for selected vectors and environment')
    print(json.dumps({'mode': args.mode, 'max_read_mib': args.max_read_mib,
                      'full_scan_estimated_seconds_with_headroom': estimate,
                      'process_memory_limit_gib': 6, 'scan_seconds_limit': 3600}))
