"""Regression checks for bounded indexing, private state and session holdout."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from acoustic_lab import FEATURE_NAMES, SCHEMA_VERSION
from acoustic_lab.cli import main
from acoustic_lab.core import (empty_sessions, index_directory, load_library,
                               load_sessions, new_session, rate, recommend,
                               train_ranker, write_json, normalization, distance_vector)
from test_core import fake_lib, feat


def labeled_sessions(lib):
    data = empty_sessions()
    for i, (seed, yes, no) in enumerate([
        ('slow', 'slow-good', 'slow-bad'),
        ('medium', 'mid-good', 'mid-bad'),
        ('fast', 'fast-good', 'fast-bad'),
    ] * 3):
        sid = f'session-{i}'
        new_session(data, sid, [seed], lib)
        rate(data, sid, yes, True, lib)
        rate(data, sid, no, False, lib)
    return data


class RegressionTests(unittest.TestCase):
    def test_multiple_octave_seeds_do_not_create_artificial_tempo(self):
        means, scales = normalization(fake_lib())
        for tempo in (70, 140):
            d = distance_vector(feat(tempo), [feat(70), feat(140)], means, scales)
            self.assertEqual(d[FEATURE_NAMES.index('bpm')], 0)

    def test_training_can_learn_a_preference_opposed_to_prior(self):
        lib = fake_lib()
        lib['tracks']['slow']['features'] = feat(tempo=100, bright=1000)
        lib['tracks']['slow-good']['features'] = feat(tempo=140, bright=1000)
        lib['tracks']['slow-bad']['features'] = feat(tempo=100, bright=2000)
        data = empty_sessions()
        for i in range(9):
            sid = f'brightness-{i}'
            new_session(data, sid, ['slow'], lib)
            rate(data, sid, 'slow-good', True, lib)
            rate(data, sid, 'slow-bad', False, lib)
        report = train_ranker(lib, data)['training']
        self.assertLess(report['baseline_holdout_pair_accuracy'], report['learned_holdout_pair_accuracy'])

    def test_failures_consume_index_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'audio'
            root.mkdir()
            for i in range(5):
                (root / f'{i}.wav').write_bytes(b'not audio')
            with patch('acoustic_lab.audio.extract_file', side_effect=ValueError('bad')) as extract:
                report = index_directory(root, Path(td) / 'state', max_files=2)
            self.assertEqual(extract.call_count, 2)
            self.assertEqual(len(report['errors']), 2)
            self.assertEqual(report['processed'], 0)

    def test_invalid_seconds_refused_even_without_audio(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                index_directory(Path(td), Path(td) / 'state', max_seconds=0)

    def test_storage_failure_not_reported_as_decode_success(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'one.wav').write_bytes(b'placeholder')
            with patch('acoustic_lab.audio.extract_file', return_value=feat()), \
                 patch('acoustic_lab.core.write_json', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    index_directory(Path(td), Path(td) / 'state')

    def test_failed_atomic_write_keeps_old_state_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'state.json'
            write_json(path, {'old': True})
            old = path.read_bytes()
            with patch('acoustic_lab.core.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    write_json(path, {'new': True})
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(list(Path(td).glob('.tmp-*')), [])
            with self.assertRaises(ValueError):
                write_json(path, {'bad': float('nan')})
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(list(Path(td).glob('.tmp-*')), [])

    def test_cache_and_missing_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'audio'
            root.mkdir()
            path = root / 'one.wav'
            path.write_bytes(b'placeholder')
            state = Path(td) / 'state'
            with patch('acoustic_lab.audio.extract_file', return_value=feat()) as extract:
                self.assertEqual(index_directory(root, state)['processed'], 1)
                self.assertEqual(index_directory(root, state)['skipped'], 1)
                self.assertEqual(extract.call_count, 1)
                self.assertEqual(index_directory(root, state, max_seconds=90)['processed'], 1)
            with self.assertRaises(OSError):
                index_directory(root / 'missing', state)

    def test_cli_partial_index_is_failure(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            with patch('acoustic_lab.cli.index_directory', return_value={'errors': [{'name': 'x'}]}):
                self.assertEqual(main(['--workspace', td, 'index', td]), 2)

    def test_corrupt_local_state_is_clean_cli_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for bad in [[], {'version': SCHEMA_VERSION, 'feature_names': list(FEATURE_NAMES), 'tracks': []},
                        {'version': SCHEMA_VERSION, 'feature_names': list(FEATURE_NAMES), 'tracks': {'x': None}}]:
                (root / 'library.json').write_text(json.dumps(bad))
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--workspace', td, 'list']), 2)
            write_json(root / 'library.json', fake_lib())
            for bad in [{'version': SCHEMA_VERSION, 'sessions': [None]},
                        {'version': SCHEMA_VERSION, 'sessions': 'invalid'}]:
                (root / 'sessions.json').write_text(json.dumps(bad))
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['--workspace', td, 'train']), 2)

    def test_invalid_model_refused_instead_of_nan_ranking_or_baseline(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        model = train_ranker(lib, data)
        session = data['sessions'][0]
        for index, bad in enumerate([{}, [], {**model, 'weights': [float('nan')] * len(FEATURE_NAMES)},
                    {**model, 'weights': [-1.] * len(FEATURE_NAMES)},
                    {**model, 'scales': [0.] * len(FEATURE_NAMES)},
                    {**model, 'weights': [1.]}, {**model, 'means': None}]):
            with self.subTest(case=index), self.assertRaises(ValueError):
                recommend(lib, session, bad)

    def test_cli_corrupt_model_never_becomes_untrained_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = fake_lib()
            data = labeled_sessions(lib)
            write_json(root/'library.json', lib)
            write_json(root/'sessions.json', data)
            for content in ('null', '{}', '{broken'):
                (root/'model.json').write_text(content)
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(['--workspace', td, 'recommend', 'session-0']), 2)
                self.assertNotIn('RANKER:', out.getvalue())

    def test_unknown_tempo_and_zero_weights_are_not_explained_as_matches(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        model = train_ranker(lib, data)
        model['weights'][FEATURE_NAMES.index('beat_regularity')] = 0
        lib['tracks']['other']['features']['bpm'] = 0
        rows = recommend(lib, data['sessions'][0], model)
        other = next(r for r in rows if r['id'] == 'other')
        self.assertNotIn('bpm', other['closest_features'])
        self.assertNotIn('beat_regularity', other['closest_features'])

    def test_malformed_ids_and_duplicate_feedback(self):
        lib = fake_lib()
        data = empty_sessions()
        for sid in ['', '../escape', 'a/b', 'a' * 81]:
            with self.assertRaises(ValueError):
                new_session(data, sid, ['slow'], lib)
        new_session(data, 'ok', ['slow'], lib)
        with self.assertRaises(ValueError):
            rate(data, 'ok', 'missing', True, lib)
        with self.assertRaises(ValueError):
            rate(data, 'ok', 'slow-good', 'no', lib)
        rate(data, 'ok', 'slow-good', True, lib)
        rate(data, 'ok', 'slow-good', True, lib)
        rate(data, 'ok', 'slow-good', False, lib)
        self.assertEqual(data['sessions'][0]['ratings'], {'slow-good': False})

    def test_training_ignores_unrated_library_tracks(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        before = train_ranker(lib, data)
        lib['tracks']['unseen'] = {'name': 'Unseen', 'features': feat(bright=1e6, energy=-90)}
        after = train_ranker(lib, data)
        for key in ['means', 'scales', 'weights', 'training']:
            self.assertEqual(before[key], after[key], key)

    def test_chronological_split_is_independent_of_json_order(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        for s in data['sessions'][-3:]:
            s['ratings'] = {k: not v for k, v in s['ratings'].items()}
        before = train_ranker(lib, data)
        data['sessions'].reverse()
        after = train_ranker(lib, data)
        for key in ['means', 'scales', 'weights', 'training']:
            self.assertEqual(before[key], after[key], key)

    def test_feedback_after_holdout_start_cannot_leak_into_training(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        rate(data, 'session-0', 'slow-good', False, lib)
        rate(data, 'session-0', 'slow-bad', True, lib)
        with self.assertRaisesRegex(ValueError, 'overlaps holdout'):
            train_ranker(lib, data)

    def test_invalid_sessions_and_less_than_six_rejected(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        with self.assertRaisesRegex(ValueError, 'Need 6 sessions'):
            train_ranker(lib, {**data, 'sessions': data['sessions'][:5]})
        for mutate in [lambda d: d['sessions'].append(d['sessions'][0]),
                       lambda d: d['sessions'][0]['ratings'].update({'slow-good': 'yes'}),
                       lambda d: d['sessions'][0].update({'created_at': 'yesterday'})]:
            bad = copy.deepcopy(data)
            mutate(bad)
            with self.assertRaises(ValueError):
                train_ranker(lib, bad)

    def test_holdout_features_do_not_fit_normalization(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        before = train_ranker(lib, data)
        for s in data['sessions'][-3:]:
            for f in s['rating_features'].values():
                f['brightness'] = 100000
        after = train_ranker(lib, data)
        self.assertEqual(before['scales'], after['scales'])
        self.assertEqual(before['weights'], after['weights'])

    def test_session_context_and_votes_survive_reindex(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        before = train_ranker(lib, data)
        for row in lib['tracks'].values():
            row['features'] = feat(bright=10000, energy=-90)
        after = train_ranker(lib, data)
        for key in ['means', 'scales', 'weights', 'training']:
            self.assertEqual(before[key], after[key], key)

    def test_holdout_labels_do_not_fit_weights(self):
        lib = fake_lib()
        data = labeled_sessions(lib)
        before = train_ranker(lib, data)
        for session in data['sessions'][-3:]:
            session['ratings'] = {k: not v for k, v in session['ratings'].items()}
        after = train_ranker(lib, data)
        self.assertEqual(before['weights'], after['weights'])
        self.assertEqual(before['scales'], after['scales'])
        self.assertNotEqual(before['training']['learned_holdout_pair_accuracy'],
                            after['training']['learned_holdout_pair_accuracy'])


if __name__ == '__main__':
    unittest.main()
