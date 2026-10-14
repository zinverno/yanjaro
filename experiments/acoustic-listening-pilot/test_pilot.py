"""Contract tests use only explicitly technical, in-memory response fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import pilot as p


def test_package():
    return dict(schema=p.SCHEMA, kind='technical-test-only', reviewer='TEST_ONLY_REVIEWER',
                package='TEST_ONLY_PACKAGE', trials=[dict(token=f'TEST_ONLY_{i}') for i in range(14)])


class PilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.frozen = p.verify_freeze()

    def test_original_inputs_and_reproducible_selection(self):
        self.assertEqual(self.frozen, p.make_freeze())
        pi, acoustic = p.frozen_inputs()
        self.assertEqual(self.frozen['cases'], p.select_cases(dict(reversed(list(pi.items()))),
                                                            dict(reversed(list(acoustic.items())))))

    def test_unique_quotas_all_ten_anchors_no_labels(self):
        cases = self.frozen['cases']
        self.assertEqual(len({(c['anchor'], *c['candidates']) for c in cases}), 12)
        self.assertEqual(len({c['anchor'] for c in cases}), 10)
        self.assertEqual(set(p.Counter(c['category'] for c in cases).values()), {2})
        self.assertIsNone(self.frozen['ground_truth'])
        for c in cases:
            self.assertEqual(len({c['anchor'], *c['candidates']}), 3)
            self.assertNotIn('answer', c); self.assertNotIn('correct_answer', c)

    def test_balanced_separated_complementary_repeats(self):
        cases = {c['case_id']: c for c in self.frozen['cases']}
        maps = []
        for slot in (1, 2):
            rows = p.schedule(list(cases.values()), slot)
            self.assertEqual(rows, p.schedule(list(reversed(list(cases.values()))), slot))
            self.assertEqual(len({r['token'] for r in rows}), 14)
            canonical_a = lambda r: r['A'] == cases[r['case_id']]['candidates'][0]
            self.assertEqual(sum(canonical_a(r) for r in rows), 7)
            self.assertEqual(sum(canonical_a(r) for r in rows if not r['repeat']), 6)
            first = {}
            for i, r in enumerate(rows):
                if r['repeat']:
                    j, initial = first[r['case_id']]
                    self.assertGreaterEqual(i - j, 4)
                    self.assertEqual((r['A'], r['B']), (initial['B'], initial['A']))
                else: first[r['case_id']] = (i, r)
            maps.append({cid: r['A'] for cid, (_, r) in first.items()})
        self.assertTrue(all(maps[0][cid] != maps[1][cid] for cid in cases))

    def test_empty_response_has_no_implied_answers(self):
        package = test_package(); response = p.empty_response(package)
        p.validate_response(response, package, allow_test=True)
        self.assertTrue(all(r['choice'] is None and r['confidence'] is None for r in response['responses']))
        with self.assertRaisesRegex(ValueError, 'not human evidence'): p.validate_response(response, package)

    def test_response_fields_and_cross_reviewer_rejected(self):
        package = test_package(); state = p.empty_response(package)
        for field, value in [('correct_answer', 'A'), ('name', 'forbidden'), ('scores', [1, 2])]:
            altered = copy.deepcopy(state); altered[field] = value
            with self.assertRaises(ValueError): p.validate_response(altered, package, allow_test=True)
        for change in ({'reviewer': 'OTHER'}, {'package': 'OTHER'}, {'position': True}):
            with self.assertRaises(ValueError): p.validate_response(dict(state, **change), package, allow_test=True)
        for change in ({'token': 'OTHER'}, {'choice': 'correct'}, {'confidence': True}, {'aspect': 'genre'}):
            altered = copy.deepcopy(state); altered['responses'][0].update(change)
            with self.assertRaises(ValueError): p.validate_response(altered, package, allow_test=True)

    def test_partial_contract_roundtrip_in_memory_only(self):
        # Mechanical enum transport, not listening data; analyzer explicitly rejects this kind.
        package = test_package(); state = p.empty_response(package)
        for choice in p.CHOICES:
            state['responses'][0]['choice'] = choice
            self.assertEqual(p.validate_response(json.loads(json.dumps(state)), package, allow_test=True), state)
        self.assertEqual(sum(r['choice'] is None for r in state['responses']), 13)

    def test_empty_anonymous_json_csv_roundtrip(self):
        package = test_package(); state = p.empty_response(package)
        with tempfile.TemporaryDirectory() as folder:
            for ext, data in [('json', json.dumps(state)), ('csv', p.csv_export(state))]:
                path = Path(folder)/('empty-test.'+ext); path.write_text(data)
                self.assertEqual(p.read_response(path), state)

    def test_tied_predictions_and_coverage_order(self):
        case = copy.deepcopy(self.frozen['cases'][0]); a, b = case['candidates']
        case['frozen_pairs'][b]['pi_v1']['distance'] = case['frozen_pairs'][a]['pi_v1']['distance']
        self.assertIsNone(p.prediction(case, 'pi_v1'))
        pa, pb = [case['frozen_pairs'][tid]['acoustic_v1'] for tid in (a,b)]
        pb['coverage_mask'] = pa['coverage_mask']; pb['common_distance'] = pa['common_distance']
        self.assertIsNone(p.prediction(case, 'acoustic_v1'))
        pb['coverage_mask'] = '111111111'; pa['rank'] = 9; pb['rank'] = 1
        self.assertEqual(p.prediction(case, 'acoustic_v1'), b)

    def test_empty_analysis_is_not_run(self):
        with tempfile.TemporaryDirectory() as folder:
            key = Path(folder)/'key.json'
            p.write_new(key, dict(frozen_sha256=p.digest(self.frozen), reviewers={}))
            report = p.analyze(key, [])
            self.assertEqual(report['status'], 'NOT RUN')
            self.assertEqual(report['answered_unique_presentations'], 0)
            self.assertEqual(report['reviewers'], [])

    def test_script_has_no_network_or_correct_answer_logic(self):
        js = (p.HERE/'app.js').read_text()
        for text in ('fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket', 'correct_answer', 'frozen_pairs'):
            self.assertNotIn(text, js)
        page = (p.HERE/'page.html').read_text()
        self.assertIn("connect-src 'none'", page)
        self.assertNotIn(' checked', page)


if __name__ == '__main__': unittest.main()
