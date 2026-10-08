"""Offline CLI smoke using generated waveforms only; prints aggregate JSON evidence.

Run: .venv/bin/python scripts/synthetic_smoke.py
No real recordings, account data, downloads or persistent model artifacts.
"""
import contextlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import wave

import numpy as np
from acoustic_lab.cli import main
from acoustic_lab.core import load_library


def run():
    network_attempts = []

    def reject_network(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
            network_attempts.append(event)
            raise RuntimeError('Network forbidden in synthetic smoke')

    sys.addaudithook(reject_network)
    with tempfile.TemporaryDirectory(prefix='yanjaro-synthetic-') as td:
        root = Path(td)
        audio, workspace = root / 'generated', root / 'state'
        audio.mkdir()
        sr, seconds = 16000, 12
        t = np.arange(sr * seconds) / sr
        for group, bpm in enumerate((60, 120, 180)):
            for variant in range(4):
                period = 60 / bpm
                signal = .12 * np.sin(2 * np.pi * (220 + 110 * group + 5 * variant) * t)
                signal += .5 * (np.mod(t, period) < .025)
                samples = (signal * 32767).astype('<i2')
                with wave.open(str(audio / f'pulse-{group}-{variant}.wav'), 'wb') as out:
                    out.setparams((1, 2, sr, len(samples), 'NONE', 'not compressed'))
                    out.writeframes(samples.tobytes())

        cli_calls = 0

        def cli(*args, expected=0):
            nonlocal cli_calls
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                result = main(['--workspace', str(workspace), *map(str, args)])
            assert result == expected, (args, result, errors.getvalue())
            cli_calls += 1
            return output.getvalue()

        assert 'empty' in cli('list').lower()
        cli('train', expected=2)
        assert not (workspace / 'model.json').exists()
        start = time.perf_counter()
        indexed = json.loads(cli('index', audio, '--limit', 12, '--seconds', 10))
        indexing_seconds = time.perf_counter() - start
        assert indexed['processed'] == 12 and not indexed['errors'], indexed
        start = time.perf_counter()
        cached = json.loads(cli('index', audio, '--limit', 12, '--seconds', 10))
        cache_seconds = time.perf_counter() - start
        assert cached['processed'] == 0 and cached['skipped'] == 12, cached
        assert len(cli('list').splitlines()) == 12
        lib = load_library(workspace / 'library.json')
        ids = {row['name']: id for id, row in lib['tracks'].items()}
        for i in range(9):
            group = i % 3
            seed = ids[f'pulse-{group}-0']
            good = ids[f'pulse-{group}-1']
            bad = ids[f'pulse-{(group + 1) % 3}-2']
            sid = f'synthetic-{i}'
            cli('new-session', sid, seed)
            if i == 0:
                assert 'not yet trained' in cli('recommend', sid)
            cli('rate', sid, good, 'yes')
            cli('rate', sid, bad, 'no')
        start = time.perf_counter()
        cli('train')
        training_seconds = time.perf_counter() - start
        model = json.loads((workspace / 'model.json').read_text())
        cli('train')
        again = json.loads((workspace / 'model.json').read_text())
        assert model['weights'] == again['weights'] and model['training'] == again['training']
        assert 'RANKER: learned' in cli('recommend', 'synthetic-0')
        assert set(model['training']['train_session_ids']).isdisjoint(model['training']['holdout_session_ids'])
        assert not network_attempts, network_attempts
        assert not any(name == 'yandex_music' or name.startswith('yandex_music.') for name in sys.modules)
        assert {p.suffix for p in workspace.iterdir()} == {'.json'}
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in workspace.iterdir())
        print(json.dumps({
            'status': 'PASS', 'data': 'generated pulse-plus-tone WAVs and scripted votes; no human quality inference',
            'python': platform.python_version(),
            'packages': {name: importlib.metadata.version(name) for name in ('numpy', 'librosa', 'soundfile', 'numba', 'scipy')},
            'generated_files': 12, 'generated_seconds_per_file': seconds, 'analyzed_seconds_per_file': 10,
            'features_per_track': len(lib['feature_names']), 'index': indexed, 'cache': cached,
            'cli_calls': cli_calls, 'network_attempts': len(network_attempts),
            'indexing_seconds': round(indexing_seconds, 3), 'cache_seconds': round(cache_seconds, 3),
            'training_seconds': round(training_seconds, 3), 'training': model['training'],
            'estimated_bpms': [round(row['features']['bpm'], 3) for _, row in sorted(lib['tracks'].items(), key=lambda p: p[1]['name'])],
            'repeat_fit_identical': True, 'private_json_only': True,
        }, indent=2))


if __name__ == '__main__':
    run()
