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


def check_frozen_tree(commit):
    # CI builds a pinned release: never report a changed application's HEAD green.
    paths = ['yanjaro', 'tests', 'pyproject.toml', 'requirements.lock', 'MANIFEST.in',
             'LICENSE', 'LICENSE-STATUS.md', 'packaging/yanjaro',
             'packaging/yanjaro.desktop', 'packaging/sdk-source.json', 'packaging/PKGBUILD.in']
    changed = subprocess.check_output(['git', 'diff', '--name-only', commit, '--', *paths],
                                      cwd=ROOT, text=True).splitlines()
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '--', *paths],
                                        cwd=ROOT, text=True).splitlines()
    assert not changed and not untracked, 'Frozen release differs from checkout: ' + ', '.join(changed + untracked)


def prepare(output):
    inputs = json.loads((ROOT / 'packaging/clean-inputs.json').read_text())
    manifest = inputs['candidate'].get('manifest', 'candidate-rc2-3.json')
    assert Path(manifest).name == manifest and manifest.endswith('.json')
    candidate = json.loads((ROOT / 'packaging' / manifest).read_text())
    source_version = inputs['candidate']['version'].rsplit('-', 1)[0]
    assert inputs['candidate']['source_commit'] == candidate['source_commit']
    assert inputs['candidate']['source_date_epoch'] == candidate['source_date_epoch']
    assert inputs['candidate']['version'] == candidate['version']
    assert inputs['candidate']['source_sha256'] == candidate['artifacts'][f'dist/native/yanjaro-{source_version}.tar.gz']
    assert re.fullmatch('[0-9a-f]{40}', candidate['source_commit']), 'Input must pin a full Git commit'
    check_frozen_tree(candidate['source_commit'])
    output.mkdir(parents=True, exist_ok=False)
    for name, spec in inputs.items():
        commit = spec['source_commit']
        assert re.fullmatch('[0-9a-f]{40}', commit), 'Input must pin a full Git commit'
        assert subprocess.check_output(['git', 'rev-parse', commit + '^{commit}'], cwd=ROOT, text=True).strip() == commit
        subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(output / (name + '.git.tar')), commit], cwd=ROOT, check=True)
    for name in ('PKGBUILD', '.SRCINFO', 'clean-inputs.json'):
        shutil.copyfile(ROOT / 'packaging' / name, output / name)
    shutil.copyfile(ROOT / 'packaging' / manifest, output / 'candidate-manifest.json')
    shutil.copytree(ROOT / 'packaging/aur', output / 'aur')
    for name in ('clean-container.sh', 'smoke-installed.py', 'check-package.py'):
        shutil.copyfile(ROOT / 'scripts' / name, output / name)
    sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(output)}\n'
                   for p in sorted(output.rglob('*')) if p.is_file())
    (output / 'SHA256SUMS').write_text(sums)
    return inputs


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
