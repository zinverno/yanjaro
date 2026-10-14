"""Authorized cap2 boundaries and failure paths; no source network or new real fit."""
import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import zipfile

import numpy as np

from acoustic_similarity.cap2 import (ARTIFACT, AUTHORIZATION, BASE_HEAD, BUNDLE_LIMIT, BoundedSource, INPUT_BYTES, LIMIT,
    LOG_DOWNLOAD_LIMIT, NoRedirect, PLAN, RESERVE, RUN_NUMBER, SOURCE_BYTES, bundle, counts, guard,
    inputs, preflight, run, score, validate_annotations)
from acoustic_similarity.data import write_new
from acoustic_similarity.diagnostics import ARTIFACT_SHA
from acoustic_similarity.groove import RangeZip

ROOT = Path(__file__).parents[1]


class Cap2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.dev, cls.integrity, cls.old = inputs()
        cls.pre = json.loads((ROOT/'validation/groove-cap2-v1/preflight-local.json').read_text())

    def test_frozen_inputs_and_real_midi_preflight(self):
        self.assertEqual(self.integrity['archive_sha256'], ARTIFACT_SHA)
        self.assertEqual(self.pre['counts'], {'originals': 3, 'bars': 12, 'triplets': 29})
        self.assertEqual(validate_annotations(self.pre['rows'], self.old), self.pre['triplets'])
        with self.assertRaisesRegex(ValueError, 'archive mismatch'):
            preflight(b'not official data', self.plan, self.old)

    def test_inadequate_comparisons_or_overlap_stop_before_audio(self):
        rows = copy.deepcopy(self.pre['rows'])
        for r in rows: r['target'] = rows[0]['target']
        with self.assertRaisesRegex(ValueError, 'fewer than 20'):
            validate_annotations(rows, self.old)
        for field, value in [('midi_sha256', next(iter(self.old.values()))['midi_sha256']), ('bpm', 89), ('drummer', 'drummer8')]:
            rows = copy.deepcopy(self.pre['rows']); rows[0][field] = value
            with self.assertRaises(ValueError): validate_annotations(rows, self.old)
        with self.assertRaises(ValueError): validate_annotations(self.pre['rows'][:-4], self.old)

    def test_exact_budget_and_output_reserve(self):
        p = self.plan
        source = p['sources']['midi_bytes']+p['sources']['directory_bytes']
        source += sum(r['compressed_bytes']+30+r['member_name_read_bytes'] for r in p['new_test']['records'])
        self.assertEqual(source, SOURCE_BYTES)
        self.assertLessEqual(SOURCE_BYTES+INPUT_BYTES+RESERVE, LIMIT)
        self.assertLess(4*((BUNDLE_LIMIT+2)//3)+LOG_DOWNLOAD_LIMIT, RESERVE//2)

    def test_budget_and_unapproved_source_fail_before_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = BoundedSource(self.plan, Path(tmp)/'receipt.json')
            client.opener = MagicMock()
            client.received = SOURCE_BYTES
            with self.assertRaisesRegex(ValueError, 'budget'): client.fetch(client.plan['midi_url'], client.plan['midi_bytes'])
            client.received = 0
            with self.assertRaisesRegex(ValueError, 'Unapproved'): client.fetch('https://example.invalid', 1)
            with self.assertRaisesRegex(ValueError, 'Unapproved'): client.fetch(client.plan['audio_url'], 1, 0)
            client.opener.open.assert_not_called()

    def test_network_error_is_single_attempt_and_partial_receipt_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'receipt.json'
            client = BoundedSource(self.plan, path)
            client.opener = MagicMock()
            client.opener.open.side_effect = urllib.error.URLError('unit failure')
            with self.assertRaises(urllib.error.URLError): client.fetch(client.plan['midi_url'], client.plan['midi_bytes'])
            with self.assertRaisesRegex(ValueError, 'Repeated'): client.fetch(client.plan['midi_url'], client.plan['midi_bytes'])
            self.assertEqual(client.opener.open.call_count, 1)
            receipt = json.loads(path.read_text())
            self.assertEqual(receipt['requests'][0]['status'], 'FAIL')
            self.assertEqual(receipt['received_source_bytes'], 0)

    def test_truncated_response_counts_received_bytes_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = BoundedSource(self.plan, Path(tmp)/'receipt.json')
            response = MagicMock(); response.__enter__.return_value = response
            response.geturl.return_value = client.plan['midi_url']; response.status = 200
            response.headers = {'Content-Length': str(client.plan['midi_bytes'])}
            response.read.side_effect = [b'abc', b'']
            client.opener = MagicMock(); client.opener.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'Truncated'): client.fetch(client.plan['midi_url'], client.plan['midi_bytes'])
            self.assertEqual(client.received, 3)
            self.assertEqual(client.opener.open.call_count, 1)

    def test_no_redirect_or_full_archive_fallback(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://example.invalid'))
        with tempfile.TemporaryDirectory() as tmp:
            client = BoundedSource(self.plan, Path(tmp)/'receipt.json')
            response = MagicMock(); response.__enter__.return_value = response
            response.geturl.return_value = client.plan['audio_url']; response.status = 200
            client.opener = MagicMock(); client.opener.open.return_value = response
            with self.assertRaisesRegex(ValueError, 'status'):
                client.fetch(client.plan['audio_url'], client.plan['directory_bytes'], client.plan['directory_offset'])
            response.read.assert_not_called()

    def test_approved_range_tracks_exact_bytes_and_rejects_etag_change(self):
        for etag_ok in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                client = BoundedSource(self.plan, Path(tmp)/'receipt.json')
                start, size = client.records[0]['header_offset'], 30
                response = MagicMock(); response.__enter__.return_value = response
                response.geturl.return_value = client.plan['audio_url']; response.status = 206
                response.headers = {'Content-Length': str(size), 'ETag': client.plan['audio_etag'] if etag_ok else 'changed',
                                    'Content-Range': f'bytes {start}-{start+size-1}/{client.plan["audio_bytes"]}'}
                response.read.return_value = b'x'*size
                client.opener = MagicMock(); client.opener.open.return_value = response
                if etag_ok:
                    self.assertEqual(client.fetch(client.plan['audio_url'], size, start), b'x'*size)
                    self.assertEqual(client.received, size)
                else:
                    with self.assertRaisesRegex(ValueError, 'changed'): client.fetch(client.plan['audio_url'], size, start)
                    response.read.assert_not_called()

    def test_one_run_number_attempt_parent_and_pr_only(self):
        env = {'CAP2_AUTHORIZATION': AUTHORIZATION, 'GITHUB_ACTIONS': 'true', 'GITHUB_RUN_NUMBER': RUN_NUMBER, 'GITHUB_RUN_ATTEMPT': '1',
               'GITHUB_JOB': 'cap2-pilot', 'GITHUB_REPOSITORY': 'zinverno/yanjaro', 'GITHUB_EVENT_NAME': 'pull_request',
               'GITHUB_WORKFLOW_REF': 'zinverno/yanjaro/.github/workflows/acoustic-similarity.yml@refs/pull/10/merge',
               'SOURCE_COMMIT': 'a'*40, 'OPENBLAS_NUM_THREADS': '2', 'OMP_NUM_THREADS': '2', 'NUMBA_NUM_THREADS': '2'}
        event = {'number': 10, 'action': 'synchronize', 'pull_request': {'head': {'repo': {'full_name': 'zinverno/yanjaro'},
                   'ref': 'experiment/acoustic-similarity-v01', 'sha': 'a'*40}}}
        guard(env, event, 'a'*40, BASE_HEAD)
        for key, value in [('GITHUB_RUN_NUMBER', '5'), ('GITHUB_RUN_NUMBER', '10'), ('CAP2_AUTHORIZATION', ''),
                           ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_JOB', 'tests'), ('OMP_NUM_THREADS', '4')]:
            with self.assertRaises(ValueError): guard({**env, key:value}, event, 'a'*40, BASE_HEAD)
        with self.assertRaises(ValueError): guard(env, event, 'a'*40, 'b'*40)
        with self.assertRaises(ValueError): guard(env, {**event, 'number': 11}, 'a'*40, BASE_HEAD)
        with patch.dict('os.environ', {}, clear=True), patch('urllib.request.build_opener') as network:
            with self.assertRaisesRegex(ValueError, 'authorized Actions'): run()
            network.assert_not_called()

    def test_correct_tie_incorrect_counts_and_same_comparisons(self):
        self.assertEqual(counts([-1., 0., 1., 1e-13]), {'comparisons': 4, 'correct': 1, 'ties': 2, 'incorrect': 1, 'accuracy': .5})
        result = score(self.dev, 'validation', np.ones(128)/128)
        self.assertEqual(result['uniform'], result['cap2'])
        self.assertEqual(result['uniform']['comparisons'], 247)
        self.assertEqual(result['uniform']['correct'], 227)
        self.assertEqual(result['uniform']['ties'], 0)
        self.assertEqual(sum(r['uniform']['comparisons'] for r in result['by_component']), 247)
        self.assertEqual(sum(r['anchor_uniform']['comparisons'] for r in result['by_original'] if r['anchor_uniform']), 247)

    def test_workflow_limit_and_single_use_guard_are_consistent(self):
        workflow = (ROOT.parents[1]/'.github/workflows/acoustic-similarity.yml').read_text()
        block = workflow.split('  cap2-pilot:', 1)[1]
        self.assertTrue(f'github.run_number == {RUN_NUMBER} && github.run_attempt == 1' in block or
                        'if: ${{ false }}' in block)
        for value in ('timeout-minutes: 10', 'ulimit -v 4194304', 'ulimit -t 600',
                      '--retries 0', 'timeout --kill-after=10s 540s', '--depth=2'):
            self.assertIn(value, block)
        self.assertNotIn('upload-artifact@', block)

    def test_bundle_contains_only_allowlisted_json_and_no_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_new(output/'status.json', {'status':'UNIT TEST ONLY'})
            text = io.StringIO()
            with patch('sys.stdout', text): bundle(output)
            raw = base64.b64decode(''.join(line.split(' ', 1)[1] for line in text.getvalue().splitlines() if line.startswith('CAP2_RESULT_DATA ')))
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                self.assertEqual(set(z.namelist()), {'status.json', 'hashes.json'})
            self.assertLess(len(raw), BUNDLE_LIMIT)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp); write_new(output/'unexpected.json', {'bad': True})
            with self.assertRaisesRegex(ValueError, 'Unexpected'): bundle(output)


if __name__ == '__main__': unittest.main()
