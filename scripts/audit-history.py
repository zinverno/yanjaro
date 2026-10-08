#!/usr/bin/env python3
"""Read-only pre-upload inventory. Prints paths/categories, never matched values.

This is a heuristic scan, not a proof that arbitrary secrets are absent.
Review every unique image separately; synthetic test literals need manual review.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('repository', type=Path)
parser.add_argument('--images', type=Path, help='extract unique historical images for manual review')
args = parser.parse_args()

def git(*arguments):
    return subprocess.check_output(['git', '-C', str(args.repository), *arguments])

rules = {
    'OAuth/GitHub token': rb'\b(?:y[01]_|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{24,}',
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'JWT': rb'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}',
    'literal credential': rb'''(?i)(?:access_token|refresh_token|device_code|user_code|password|cookie|authorization)["']?\s*[:=]\s*["']([^"'\r\n]{4,})["']''',
    'signed service audio': rb'https?://[^\s"<>]+(?:/get-mp3/|/get-opus/|[?&](?:sign|signature|token|expires)=)[^\s"<>]+',
}
findings, images, scanned = [], [], 0
objects = git('rev-list', '--objects', '--all').decode().splitlines()
for record in objects:
    sha, _, name = record.partition(' ')
    kind = git('cat-file', '-t', sha).strip()
    if kind not in (b'blob', b'commit'):
        continue
    data = git('cat-file', kind.decode(), sha)
    scanned += 1
    label = name or '(commit metadata)'
    if kind == b'blob' and Path(name).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
        images.append({'object': sha, 'path': name})
        if args.images:
            args.images.mkdir(parents=True, exist_ok=True)
            (args.images / (sha + Path(name).suffix)).write_bytes(data)
        continue
    if b'\0' in data:
        findings.append({'object': sha, 'path': label, 'category': 'unreviewed binary'})
        continue
    for category, pattern in rules.items():
        for match in re.finditer(pattern, data):
            findings.append({'object': sha, 'path': label, 'category': category,
                             'line': data[:match.start()].count(b'\n') + 1})
    parts = Path(name).parts
    if (any(p in ('.venv', '.runtime', '.aws', 'node_modules') or p.startswith('.env') for p in parts)
            or Path(name).suffix in ('.db', '.sqlite', '.sqlite3', '.log', '.pem', '.key', '.bundle')):
        findings.append({'object': sha, 'path': label, 'category': 'private/generated file path'})
print(json.dumps({'scanned_blobs_and_commits': scanned, 'images': images, 'review': findings}, indent=2))
raise SystemExit(bool(findings))
