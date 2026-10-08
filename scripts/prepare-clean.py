#!/usr/bin/env python3
"""Export pinned Git inputs, never untracked dist files or a user's profile."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare(output):
    inputs = json.loads((ROOT / 'packaging/clean-inputs.json').read_text())
    candidate = json.loads((ROOT / 'packaging/candidate-rc2-3.json').read_text())
    assert inputs['candidate']['source_commit'] == candidate['source_commit']
    assert inputs['candidate']['source_date_epoch'] == candidate['source_date_epoch']
    assert inputs['candidate']['version'] == candidate['version']
    assert inputs['candidate']['source_sha256'] == candidate['artifacts']['dist/native/yanjaro-0.2.0rc2.tar.gz']
    output.mkdir(parents=True, exist_ok=False)
    for name, spec in inputs.items():
        commit = spec['source_commit']
        assert re.fullmatch('[0-9a-f]{40}', commit), 'Input must pin a full Git commit'
        assert subprocess.check_output(['git', 'rev-parse', commit + '^{commit}'], cwd=ROOT, text=True).strip() == commit
        subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(output / (name + '.git.tar')), commit], cwd=ROOT, check=True)
    for name in ('PKGBUILD', '.SRCINFO', 'candidate-rc2-3.json', 'clean-inputs.json'):
        shutil.copyfile(ROOT / 'packaging' / name, output / name)
    for name in ('clean-container.sh', 'smoke-installed.py', 'check-package.py'):
        shutil.copyfile(ROOT / 'scripts' / name, output / name)
    sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                   for p in sorted(output.iterdir()))
    (output / 'SHA256SUMS').write_text(sums)
    return inputs


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
