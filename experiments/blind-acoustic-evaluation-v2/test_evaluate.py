"""Synthetic mechanics only. Never writes a human response or evaluates music."""
from collections import Counter
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evaluate as e
import numpy as np
import soundfile as sf
from acoustic_similarity import acoustic_retrieval as ar


def synthetic_rows():
    rng = np.random.default_rng(2718)
    rows = []
    for i in range(12):
        blocks = {}
        for k, n in ar.SHAPES.items():
            v = rng.random(n)
            if k in ('timbre', 'energy'): v = 2*v-1
            elif k != 'density': v /= v.sum()
            blocks[k] = v.tolist()
        rows.append(dict(id=f't{i+1:02}', audio_sha256=e.digest(['SYNTHETIC', i]),
                         recording_group=f'TEST_ONLY_{i}', feature_schema=ar.FEATURE_SCHEMA,
                         blocks=blocks, missing_reasons={}))
    return rows


def empty_response(package):
    return dict(e.pilot.empty_response(package), schema=package['schema'])


def synthetic_plan(folder):
    plan = e.template(); plan['kind'] = 'synthetic-test-only'
    plan['previous_yandex_track_ids'] = ['90001', '90002', '90003', '90004']
    plan['excluded_recording_groups'] = [f'EXCLUDED_TEST_{i}' for i in range(4)]
    evidence = folder / 'TEST_ONLY_RIGHTS.txt'; evidence.write_text('Synthetic generated fixture; no real audio.')
    for i, t in enumerate(plan['tracks']):
        audio = folder / f'TEST_ONLY_{i}.wav'
        sr = 8000; time = np.arange(15*sr)/sr
        signal = .25*np.sin(2*np.pi*(220+i*30)*time) * (.1+.9*(np.sin(2*np.pi*(2+i/10)*time)>0))
        sf.write(audio, signal, sr, subtype='FLOAT')
        t.update(path=str(audio), sha256=e.file_hash(audio), title='PRIVATE_TITLE_TEST_ONLY',
                 artist_ids=[f'TEST_ARTIST_{i%4}'], recording_group=f'TEST_ONLY_{i}', start=0, novelty_reviewed=True)
        t['rights'] = dict(reviewed=True, acquisition=True, analysis=True, local_feature_storage=True,
                           private_listening=True, license='synthetic-test-only', source_url='generated:fixture',
                           attribution='TEST_ONLY', verified_on='2026-11-13', scope='automated testing only',
                           evidence_path=str(evidence), evidence_sha256=e.file_hash(evidence))
    return plan


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = synthetic_rows()
        cls.ranked = e.rankings(cls.rows)
        cls.cases = e.select_cases(cls.ranked)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='blind-v2-TECHNICAL-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = synthetic_plan(self.root)

    def test_frozen_upstream_and_locked_runtime(self):
        self.assertEqual(e.source_hashes()['upstream']['base_commit'], 'a9fe148cc9b81fcfb76d55ea11d18b701bbd0e84')
        self.assertEqual(e.runtime()['packages']['numpy'], '2.2.6')

    def test_blank_template_and_boundaries(self):
        with self.assertRaises(ValueError): e.preflight(e.template())
        self.assertEqual(len(e.preflight(self.plan, files=True)), 12)
        for n in (0, 11, 17):
            altered = copy.deepcopy(self.plan); altered['tracks'] = (altered['tracks']*2)[:n]
            with self.assertRaises(ValueError): e.preflight(altered)

    def test_prior_recordings_and_rights_are_excluded(self):
        historical = e.read_json(e.LAB / 'validation/acoustic-retrieval-v1/index.json')['tracks'][0]
        changes = [dict(yandex_track_id='90001'), dict(recording_group='EXCLUDED_TEST_0'),
                   dict(sha256=historical['audio_sha256']), dict(recording_group=historical['recording_group']),
                   dict(novelty_reviewed=False), dict(split='train'), dict(seconds=30), dict(path='https://example/audio')]
        for change in changes:
            altered = copy.deepcopy(self.plan); altered['tracks'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): e.preflight(altered)
        for key in ('reviewed', 'acquisition', 'analysis', 'local_feature_storage', 'private_listening'):
            altered = copy.deepcopy(self.plan); altered['tracks'][0]['rights'][key] = False
            with self.subTest(key=key), self.assertRaises(ValueError): e.preflight(altered)

    def test_duplicate_identity_and_changed_evidence(self):
        for key in ('id', 'recording_group', 'sha256'):
            altered = copy.deepcopy(self.plan); altered['tracks'][1][key] = altered['tracks'][0][key]
            with self.assertRaises(ValueError): e.preflight(altered)
        altered = copy.deepcopy(self.plan)
        altered['tracks'][0]['rights']['evidence_sha256'] = '0'*64
        with self.assertRaises(ValueError): e.preflight(altered, files=True)

    def test_consent_is_required_before_extraction_and_output(self):
        plan_path = self.root / 'plan.json'; e.write_new(plan_path, self.plan)
        with patch.object(e.sys.stdin, 'isatty', return_value=False), patch.object(e, 'extract_tracks') as extract:
            with self.assertRaisesRegex(ValueError, 'interactive'): e.prepare(plan_path, self.root / 'run')
            extract.assert_not_called()
        with patch.object(e.sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='no'), \
                patch.object(e, 'extract_tracks') as extract, patch('sys.stdout', new=io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'No local consent'): e.prepare(plan_path, self.root / 'run')
            extract.assert_not_called()
        self.assertFalse((self.root / 'run').exists())

    def test_private_and_create_only_guards(self):
        with self.assertRaises(ValueError): e.private_path(e.HERE / 'private')
        nested = self.root / 'repo'; nested.mkdir(); (nested / '.git').mkdir(); (nested / '.git' / 'HEAD').write_text('ref: refs/heads/test\n')
        with self.assertRaises(ValueError): e.private_path(nested / 'private')
        file = self.root / 'original.json'; e.write_new(file, {'preserve': True})
        with self.assertRaises(FileExistsError): e.write_new(file, {})
        self.assertEqual(e.read_json(file), {'preserve': True})

    def test_rankers_equal_frozen_implementations_and_tempo_component(self):
        for alg in e.ALGORITHMS[:2]:
            self.assertEqual(self.ranked['t01'][alg], ar.search('t01', self.rows, 12, alg))
        tempo = {r['id']: r['distance'] for r in self.ranked['t01']['tempo_only']['results']}
        for row in self.rows[1:]:
            self.assertEqual(tempo[row['id']], ar.compare(self.rows[0], row)['atomic_distances']['tempo'])

    def test_missing_policy_abstention_and_ties_do_not_use_id(self):
        rows = copy.deepcopy(self.rows[:3]); rows[1]['blocks'] = copy.deepcopy(rows[2]['blocks'])
        ranked = e.rankings(rows)['t01']
        for alg in e.ALGORITHMS: self.assertEqual(e.preference(ranked, alg, 't02', 't03'), 'tie')
        rows[1]['blocks']['tempo'] = None; rows[1]['missing_reasons']['tempo'] = 'TEST_UNKNOWN'
        ranked = e.rankings(rows)['t01']
        self.assertEqual(e.preference(ranked, 'tempo_only', 't02', 't03'), 'abstain')
        self.assertEqual(e.preference(ranked, 'pi_coverage_v2', 't02', 't03'), 't03')
        self.assertEqual(e.preference(ranked, 'acoustic', 't02', 't03'), 't03')
        for k in ar.NAMES:
            rows[0]['blocks'][k] = None; rows[0]['missing_reasons'][k] = 'TEST_UNKNOWN'
        ranked = e.rankings(rows)['t01']
        for alg in e.ALGORITHMS: self.assertEqual(e.preference(ranked, alg, 't02', 't03'), 'abstain')

    def test_selection_is_reproducible_and_exact(self):
        self.assertEqual(e.select_cases(e.rankings(list(reversed(self.rows)))), self.cases)
        self.assertEqual(Counter(c['group'] for c in self.cases), {'disagreement': 6, 'consensus': 4})
        self.assertEqual(len({(c['anchor'], *c['candidates']) for c in self.cases}), 10)
        for c in self.cases:
            strict = {v for v in c['predictions'].values() if v in c['candidates']}
            self.assertEqual(len(strict), 2 if c['group'] == 'disagreement' else 1)
        with self.assertRaisesRegex(ValueError, 'insufficient'): e.select_cases({})

    def test_twelve_balanced_complementary_presentations_and_repeats(self):
        schedules = e.schedules(self.cases, 'TEST_BINDING')
        self.assertEqual(schedules, e.schedules(list(reversed(self.cases)), 'TEST_BINDING'))
        lookup = {c['case_id']: c for c in self.cases}
        first_by_slot = {}
        for slot, trials in schedules.items():
            self.assertEqual(len(trials), 12); self.assertEqual(len({t['token'] for t in trials}), 12)
            self.assertEqual(sum(t['A'] == lookup[t['case_id']]['candidates'][0] for t in trials), 6)
            first = {}; repeated = []
            for i, t in enumerate(trials):
                if t['repeat']:
                    j, initial = first[t['case_id']]
                    self.assertGreaterEqual(i-j, 4)
                    self.assertEqual((t['A'], t['B']), (initial['B'], initial['A']))
                    repeated.append(lookup[t['case_id']]['group'])
                else: first[t['case_id']] = i, t
            self.assertEqual(set(repeated), {'disagreement', 'consensus'})
            first_by_slot[slot] = first
        for cid in lookup: self.assertNotEqual(first_by_slot['1'][cid][1]['A'], first_by_slot['2'][cid][1]['A'])

    def test_actual_synthetic_waveform_extraction_and_metadata_free_wav(self):
        track = self.plan['tracks'][0]
        rows, clips, receipts = e.extract_tracks({track['id']: track})
        ar.validate(rows[0]); raw = clips[track['id']]
        self.assertEqual(raw[:4], b'RIFF'); self.assertEqual(raw[12:16], b'fmt ')
        self.assertEqual(raw[36:40], b'fact'); self.assertEqual(raw[48:52], b'data')
        self.assertEqual(len(raw), 56 + 15*8000*4)
        samples, sr = sf.read(io.BytesIO(raw), dtype='float32')
        original, _ = sf.read(track['path'], dtype='float32')
        np.testing.assert_array_equal(samples, original)
        self.assertEqual(sr, 8000); self.assertEqual(receipts[0]['clip_sha256'], hashlib.sha256(raw).hexdigest())

    def test_overshoot_is_rejected_without_clipping(self):
        track = self.plan['tracks'][0]
        sf.write(track['path'], np.ones(15*8000)*1.2, 8000, subtype='FLOAT')
        with self.assertRaisesRegex(ValueError, 'above-full-scale'): e.extract_tracks({track['id']: track})

    def prepared_fixture(self):
        plan_path = self.root / 'plan.json'; e.write_new(plan_path, self.plan)
        clips = {t['id']: Path(t['path']).read_bytes() for t in self.plan['tracks']}
        # Descriptor substitution is explicit; this tests orchestration, not acoustic quality.
        with patch.object(e.sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', return_value='INDEX '+e.digest(self.plan)[:12]), \
             patch.object(e, 'extract_tracks', return_value=(self.rows, clips, [])), \
             patch('sys.stdout', new=io.StringIO()):
            e.prepare(plan_path, self.root / 'run')
        return self.root / 'run'

    def test_freeze_separation_and_blind_projection(self):
        run = self.prepared_fixture()
        freeze, intent, predictions, packages = e.verify_run(run)
        self.assertEqual(intent['consent']['phrase'], 'INDEX '+e.digest(self.plan)[:12])
        self.assertEqual(list((run / 'responses').iterdir()), [])
        self.assertEqual(freeze['human_evaluation'], 'NOT RUN')
        self.assertEqual(len(predictions['cases']), 10)
        for slot, package in packages.items():
            self.assertEqual(package['kind'], 'technical-test-only')
            html = (run / 'listeners' / f'listener-{slot}.html').read_text()
            for forbidden in ('PRIVATE_TITLE_TEST_ONLY', 'pi_coverage_v2', 'tempo_only', 'conditional_score',
                              'recording_group', str(self.root), '"predictions":', 'coverage_mask'):
                self.assertTrue(forbidden not in html, 'Blind page leaked field: ' + forbidden)
            self.assertIn("connect-src 'none'", html)
            self.assertIn('12 коротких сравнений', html)
            self.assertEqual((run / 'listeners' / f'listener-{slot}.html').stat().st_mode & 0o777, 0o600)
        changed = run / 'organizer' / 'predictions.json'; changed.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'changed'): e.verify_run(run)

    def test_closeout_required_empty_evaluation_and_technical_response_rejected(self):
        run = self.prepared_fixture()
        closeout = e.read_json(run / 'organizer' / 'closeout.template.json')
        path = self.root / 'closeout.json'; e.write_new(path, closeout)
        with self.assertRaisesRegex(ValueError, 'must be closed'): e.analyze(run, path, [])
        closeout['slots'] = {'1': 'withdrawn', '2': 'withdrawn'}; path.write_text(json.dumps(closeout))
        self.assertEqual(e.analyze(run, path, [])['status'], 'NOT RUN')
        packages = e.read_json(run / 'organizer' / 'packages.json')
        state = empty_response(packages['1'])
        with self.assertRaisesRegex(ValueError, 'technical fixtures'): e.validate_response(state, packages['1'])
        closeout['slots']['1'] = 'completed'; path.write_text(json.dumps(closeout))
        with self.assertRaisesRegex(ValueError, 'Missing completed'): e.analyze(run, path, [])

    def test_response_contract_and_csv_roundtrip_in_memory_fixtures_only(self):
        package = dict(schema=e.SCHEMA, kind='human-self-report', reviewer='TEST_ONLY', package='TEST_ONLY',
                       trials=[dict(token=f'TEST_ONLY_{i}') for i in range(12)])
        state = empty_response(package)
        for choice in e.pilot.CHOICES:
            state['responses'][0]['choice'] = choice; e.validate_response(state, package)
        for change in ({'reviewer': 'OTHER'}, {'position': True}, {'score': 1}):
            with self.assertRaises(ValueError): e.validate_response(dict(state, **change), package)
        for change in ({'token': 'OTHER'}, {'choice': 'correct'}, {'confidence': True}, {'aspect': 'genre'}):
            altered = copy.deepcopy(state); altered['responses'][0].update(change)
            with self.assertRaises(ValueError): e.validate_response(altered, package)
        # Disk fixture is explicitly technical and rejected as human evidence.
        state['kind'] = 'technical-test-only'
        path = self.root / 'TEST_ONLY.csv'; path.write_text(e.pilot.csv_export(state))
        self.assertEqual(e.read_response(path), state)

    def test_denominators_ties_neither_uncertain_and_abstention(self):
        rows = [dict(choice=c, selected='x' if c == 'A' else 'y' if c == 'B' else c,
                     predictions=dict(acoustic='x', pi_coverage_v2='tie', tempo_only='abstain'))
                for c in ('A', 'B', 'tie', 'neither', 'uncertain', None)]
        stats = e.counts(rows)
        self.assertEqual(stats['agreement']['acoustic']['matches'], 1)
        self.assertEqual(stats['agreement']['acoustic']['eligible'], 2)
        self.assertEqual(stats['agreement']['acoustic']['fraction'], .5)
        self.assertIsNone(stats['agreement']['tempo_only']['fraction'])
        self.assertEqual(stats['agreement']['pi_coverage_v2']['exact_human_model_ties'], 1)
        self.assertEqual(set(stats['choices'].values()), {1})

    def test_listener_comparison_decodes_orientation_and_excludes_repeats(self):
        base = dict(case_id='TEST', group='disagreement', partial_features=False, aspect=None,
                    predictions={a: 'x' for a in e.ALGORITHMS})
        left = dict(base, choice='A', selected='x', canonical_choice='candidate_1', repeat=False)
        right = dict(base, choice='B', selected='x', canonical_choice='candidate_1', repeat=False)
        repeat = dict(right, repeat=True)
        result = e.summarize({'1': [left, repeat], '2': [right]})
        self.assertEqual(result['totals']['presentations'], 2)
        self.assertEqual(result['between_listeners']['decisive_disagreements'], 0)
        self.assertTrue(result['repeats'][0]['consistent'])
        right.update(selected='y', canonical_choice='candidate_2')
        self.assertEqual(e.summarize({'1': [left], '2': [right]})['between_listeners']['decisive_disagreements'], 1)

    def test_schedule_many_case_ids_and_input_orders(self):
        for n in range(100):
            cases = [dict(c, case_id=f'TEST_{n}_{i}') for i, c in enumerate(self.cases)]
            schedules = e.schedules(cases, 'TEST')
            self.assertEqual(schedules, e.schedules(list(reversed(cases)), 'TEST'))
            for trials in schedules.values():
                first = {t['case_id']: i for i, t in enumerate(trials) if not t['repeat']}
                self.assertEqual(len(first), 10)
                self.assertTrue(all(i-first[t['case_id']] >= 4 for i, t in enumerate(trials) if t['repeat']))

    def test_analysis_join_and_duplicate_guard_in_memory_only(self):
        run = self.prepared_fixture()
        frozen, intent, pred, packages = e.verify_run(run)
        # Simulate transport in memory only: never save fabricated human exports/reports.
        for p in packages.values(): p['kind'] = 'human-self-report'
        responses = []
        for slot, package in packages.items():
            response = empty_response(package)
            for i, (answer, trial) in enumerate(zip(response['responses'], pred['schedules'][slot])):
                case = next(c for c in pred['cases'] if c['case_id'] == trial['case_id'])
                answer['choice'] = 'A' if trial['A'] == case['candidates'][0] else 'B'
            responses.append(response)
        closeout = dict(schema=e.SCHEMA, seal=e.digest(frozen), slots={'1': 'completed', '2': 'completed'})
        path = self.root / 'closeout.json'; e.write_new(path, closeout)
        with patch.object(e, 'verify_run', return_value=(frozen, intent, pred, packages)), \
             patch.object(e, 'read_response', side_effect=responses), patch.object(e, 'file_hash', return_value='TEST_ONLY'):
            report = e.analyze(run, path, [Path('TEST_IN_MEMORY_1'), Path('TEST_IN_MEMORY_2')])
        self.assertEqual(report['totals']['presentations'], 20)
        self.assertEqual(report['artist_groups'], 4)
        self.assertEqual(report['between_listeners']['jointly_decisive'], 10)
        self.assertEqual(report['between_listeners']['decisive_disagreements'], 0)
        self.assertTrue(all(r['consistent'] for r in report['repeats']))
        self.assertIn('Eligible decisive', e.markdown(report))
        with patch.object(e, 'verify_run', return_value=(frozen, intent, pred, packages)), \
             patch.object(e, 'read_response', return_value=responses[0]), patch.object(e, 'file_hash', return_value='TEST_ONLY'):
            with self.assertRaisesRegex(ValueError, 'duplicate listener'):
                e.analyze(run, path, [Path('TEST_IN_MEMORY_1'), Path('TEST_DUPLICATE')])


if __name__ == '__main__': unittest.main()
