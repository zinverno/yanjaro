#!/usr/bin/env python3
"""Inspect native artifacts without reading or executing user credentials."""
import argparse
from pathlib import Path
import re
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('package', type=Path)
args=parser.parse_args()
package=args.package.resolve()
names=subprocess.check_output(['bsdtar','-tf',str(package)],text=True).splitlines()
for name in names:
    path=Path(name)
    assert not path.is_absolute() and '..' not in path.parts, name
    assert path.parts[0] in {'.PKGINFO','.BUILDINFO','.MTREE','usr'}, name
    assert not any(p in {'.venv','.runtime','.git','__pycache__','tests','node_modules'} for p in path.parts), name
    assert path.suffix not in {'.db','.sqlite','.log','.pem','.key'}, name
    assert not any(p.startswith('.env') for p in path.parts), name
required={'usr/bin/yanjaro','usr/share/applications/yanjaro.desktop',
          'usr/share/icons/hicolor/scalable/apps/yanjaro.svg',
          'usr/lib/yanjaro/yanjaro/Main.qml','usr/lib/yanjaro/yanjaro/qmldir',
          'usr/lib/yanjaro/yandex_music/__init__.py',
          'usr/lib/yanjaro/yanjaro/icons/COPYING-LGPL-3.0',
          'usr/lib/yanjaro/yanjaro/icons/COPYING-GPL-3.0',
          'usr/share/licenses/yanjaro/LICENSE',
          'usr/share/licenses/yanjaro/yandex-music-LICENSE'}
assert required.issubset(names), required-set(names)
source_root=Path(__file__).resolve().parents[1] / 'yanjaro'
expected={f'usr/lib/yanjaro/yanjaro/{p.relative_to(source_root)}'
          for p in source_root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
actual={n for n in names if n.startswith('usr/lib/yanjaro/yanjaro/') and not n.endswith('/')}
assert actual==expected, 'Application resources differ from source (possible stale build files)'
for name in names:
    if name == 'usr/bin/yanjaro' or name.startswith('usr/lib/yanjaro/yanjaro/') and Path(name).suffix in {'.py','.qml'}:
        body=subprocess.check_output(['bsdtar','-xOf',str(package),name])
        assert b'/home/zinvernix/' not in body and b'.venv/' not in body, name
        assert not re.search(rb'\by[01]_[A-Za-z0-9_-]{24,}', body), 'Possible OAuth token in ' + name
        assert not re.search(rb'https?://[^\s\x22\x27]+/(?:get-mp3|get-opus)/', body), 'Possible audio URL in ' + name
metadata=subprocess.check_output(['bsdtar','-xOf',str(package),'.PKGINFO'],text=True)
for dependency in ('pyside6','python-mpv','mpv','python-requests','qt6-svg'):
    assert any(line.startswith('depend = '+dependency) for line in metadata.splitlines()), dependency
print('PASS: native layout, entry point, resources, declared dependencies and private-file exclusions')
print('User secrets were not read; third-party SDK is a separately pinned upstream distribution.')
