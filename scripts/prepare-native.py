#!/usr/bin/env python3
"""Create a whitelisted, deterministic source snapshot and makepkg metadata. No publishing."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
out = ROOT / 'dist/native'
out.mkdir(parents=True, exist_ok=True)
archive = out / f'yanjaro-{version}.tar.gz'
epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '1791360000'))  # Candidate source date: 2026-10-07 UTC.
files = [ROOT / name for name in ('pyproject.toml', 'README.md', 'VALIDATION.md', 'LICENSE', 'LICENSE-STATUS.md', 'requirements.lock', 'run.sh', 'MANIFEST.in')]
for directory, suffixes in (('yanjaro', {'.py', '.qml', '.svg', '.json', '.md', ''}), ('tests', {'.py'}), ('scripts', {'.py', '.sh'}), ('docs', {'.md'})):
    files += [p for p in (ROOT / directory).rglob('*') if p.is_file()
              and (p.suffix in suffixes or p.name.startswith('COPYING-')) and '__pycache__' not in p.parts]
files.append(ROOT / 'docs/screenshots/login.png')  # Reviewed, credential-free real login screen only.
files += [ROOT / 'packaging' / name for name in ('yanjaro', 'yanjaro.desktop', 'sdk-source.json', 'PKGBUILD.in')]
with archive.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=epoch) as compressed, tarfile.open(fileobj=compressed, mode='w') as tar:
    for path in sorted(set(files)):
        name = f'yanjaro-{version}/{path.relative_to(ROOT)}'
        info = tar.gettarinfo(str(path), arcname=name)
        if not info.isfile():
            raise SystemExit(f'Refusing nonregular source: {path.name}')
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        info.mtime = epoch
        info.mode = 0o755 if path.name == 'yanjaro' or path.suffix == '.sh' else 0o644
        with path.open('rb') as source:
            tar.addfile(info, source)
sdk = json.loads((ROOT / 'packaging/sdk-source.json').read_text())
recipe = (ROOT / 'packaging/PKGBUILD.in').read_text().replace('@SOURCE_SHA256@', hashlib.sha256(archive.read_bytes()).hexdigest()).replace('@SDK_URL@', sdk['url']).replace('@SDK_SHA256@', sdk['sha256'])
if f'pkgver={version}\n' not in recipe:
    raise SystemExit('PKGBUILD version disagrees with pyproject.toml')
(ROOT / 'packaging/PKGBUILD').write_text(recipe)
(out / 'PKGBUILD').write_text(recipe)
metadata = subprocess.check_output(['makepkg', '--printsrcinfo'], cwd=out, text=True)
(ROOT / 'packaging/.SRCINFO').write_text(metadata)
(out / '.SRCINFO').write_text(metadata)
cache = os.environ.get('YANJARO_SOURCE_CACHE')
if cache:
    wheel = Path(cache) / sdk['filename']
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != sdk['sha256']:
        raise SystemExit('SDK checksum mismatch')
    shutil.copyfile(wheel, out / sdk['filename'])
print(f'Prepared {archive.name}, PKGBUILD and generated .SRCINFO; publication remains a separate step')
