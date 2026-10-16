"""Quality policy: synthetic PCM/MP3 in RAM, no network, account or audio files."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime
runtime.configure()

import copy
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import core
import personal_index


def tone(sr=48000, hz=220, level=.3):
    t = np.arange(12 * sr) / sr
    return (level * np.sin(2 * np.pi * hz * t))[:, None]


def legacy(row):
    row = copy.deepcopy(row)
    row['schema'] = core.STREAM_SCHEMA if row['source'] == 'yandex_stream' else core.SCHEMA
    row['quality'] = {k: row['quality'][k] for k in core.LEGACY_QUALITY_FIELDS}
    return row


class QualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normal = core.extract(tone(), 48000, 'normal', core.identity(), 'file')

    def measure(self, pcm, sr=48000):
        with patch('sys.stderr', new_callable=io.StringIO) as log:
            q = core.signal_quality(pcm, sr)
        return q, log.getvalue()

    def test_normal_and_quantized_bass_are_not_hard_clipping(self):
        for sr in (8000, 16000, 44100, 48000, 96000):
            for hz in (20, 40, 997):
                with self.subTest(sr=sr, hz=hz):
                    pcm = np.round(tone(sr, hz) * 32768) / 32768
                    before = pcm.copy()
                    q, _ = self.measure(pcm, sr)
                    self.assertEqual(q['status'], 'ACCEPTED')
                    self.assertFalse(q['long_flat_top'])
                    self.assertTrue(np.array_equal(pcm, before))
                    pcm.fill(0); before.fill(0)

    def test_full_scale_sine_occupancy_is_caution_not_clipping_proof(self):
        pcm = tone(hz=997, level=1)
        q, log = self.measure(pcm)
        self.assertGreater(q['clipped_fraction'], .001)
        self.assertEqual(q['outside_unit_samples'], 0)
        self.assertEqual(q['status'], 'ACCEPTED_WITH_CAUTION')
        self.assertEqual(q['flags'], ['HIGH_FULL_SCALE_OCCUPANCY'])
        self.assertEqual(json.loads(log)['violated_conditions'], [])
        pcm.fill(0)

    def test_small_sample_overshoot_preserves_amplitude_and_reports_counts(self):
        pcm = tone()
        pcm[200, 0], pcm[700, 0] = 1.02, -1.04
        digest = hashlib.sha256(pcm).hexdigest()
        q, log = self.measure(pcm)
        self.assertEqual(q['outside_unit_samples'], 2)
        self.assertEqual(q['peak'], 1.04)
        self.assertAlmostEqual(q['rms'], np.sqrt(np.mean(pcm**2)))
        self.assertEqual(q['flat_top_runs'], 0)
        self.assertEqual(q['flags'], ['SAMPLE_OVERSHOOT'])
        self.assertEqual(hashlib.sha256(pcm).hexdigest(), digest)
        self.assertEqual(set(json.loads(log)), set(q) | {'event', 'violated_conditions'})
        pcm.fill(0)

    def test_real_mp3_overshoot_to_705_and_private_index_repeat(self):
        sr = 48000
        t = np.arange(14 * sr) / sr
        pcm = (np.sin(2 * np.pi * 997 * t) * (.2 + .8 * ((t % .1) < .025))).astype('<f4')
        self.assertLessEqual(float(np.max(np.abs(pcm))), 1)
        command = ['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1']
        encoded = subprocess.run(command + ['-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', 'pipe:0',
            '-threads', '1', '-c:a', 'libmp3lame', '-b:a', '192k', '-f', 'mp3', 'pipe:1'],
            input=pcm.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=15).stdout
        pcm.fill(0)
        decoded = bytearray(subprocess.run(command + ['-f', 'mp3', '-i', 'pipe:0', '-f', 'f32le', 'pipe:1'],
            input=encoded, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=15).stdout)
        pcm = np.frombuffer(decoded, dtype='<f4')[sr:13 * sr, None].copy()
        np.frombuffer(decoded, dtype=np.uint8).fill(0)
        del encoded, decoded
        self.assertGreater(float(np.max(np.abs(pcm))), 1.001)
        self.assertLess(float(np.max(np.abs(pcm))), core.MAX_SAMPLE_PEAK)
        original = pcm.copy()
        with tempfile.TemporaryDirectory(dir='/tmp') as temp, patch('sys.stderr', new_callable=io.StringIO) as log:
            index = core.Index(Path(temp) / 'private')
            row = core.extract(pcm, sr, 'mp3', core.identity(), 'file', 'PRIVATE_TITLE_SENTINEL')
            self.assertTrue((pcm == 0).all())
            self.assertEqual(row['quality']['status'], 'ACCEPTED_WITH_CAUTION')
            self.assertIn('SAMPLE_OVERSHOOT', row['quality']['flags'])
            self.assertEqual(row['quality']['flat_top_runs'], 0)
            self.assertEqual(row['profile']['audio_sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(sum(len(v) for v in row['profile']['blocks'].values() if v is not None), 705)
            self.assertEqual(index.put(row), 'INSERTED')
            repeat = core.extract(original, sr, 'mp3', core.identity(), 'file', 'PRIVATE_TITLE_SENTINEL')
            self.assertEqual(repeat['profile'], row['profile'])
            self.assertTrue((original == 0).all())
            self.assertEqual(index.put(repeat), 'UNCHANGED')
            self.assertNotIn('PRIVATE_TITLE_SENTINEL', log.getvalue())
            self.assertEqual([p.name for p in index.path.parent.iterdir()], ['index.sqlite3'])
            for forbidden in (b'RIFF', b'ID3', b'https://', b'Authorization', b'cookie', b'token'):
                self.assertNotIn(forbidden, index.path.read_bytes())
            self.assertLess(len(index.path.read_bytes()), 100000)

    def test_hard_clipping_at_multiple_levels_and_channels_rejects_and_wipes(self):
        for sr in (8000, 48000, 96000):
            for hz in (40, 220, 440):
                for ceiling in (.6, 1, 1.2):
                    with self.subTest(sr=sr, hz=hz, ceiling=ceiling):
                        clipped = np.clip(tone(sr, hz, ceiling * 2), -ceiling, ceiling)
                        pcm = np.concatenate((tone(sr), clipped), axis=1)
                        with patch('sys.stderr', new_callable=io.StringIO) as log, patch('core.rhythm_pi.extract') as dsp:
                            with self.assertRaisesRegex(core.Rejected, 'FLAT_TOP_CLIPPING_SUSPECTED'):
                                core.extract(pcm, sr, 'clipped', core.identity(), 'file')
                            dsp.assert_not_called()
                        diagnostic = json.loads(log.getvalue())
                        self.assertEqual(diagnostic['status'], 'REJECTED')
                        self.assertGreater(diagnostic['flat_top_fraction'], .001)
                        self.assertIn('flat_top_runs >= 3 and flat_top_fraction >= 0.001', diagnostic['violated_conditions'])
                        self.assertTrue((pcm == 0).all())
                        clipped.fill(0)

    def test_single_long_plateau_and_short_flat_warning(self):
        for samples, reject in ((12, False), (48, True)):
            pcm = tone()
            pcm[100:100 + samples] = .9
            with patch('sys.stderr', new_callable=io.StringIO) as log:
                if reject:
                    with self.assertRaisesRegex(core.Rejected, 'FLAT_TOP_CLIPPING_SUSPECTED'):
                        core.signal_quality(pcm, 48000)
                else:
                    self.assertEqual(core.signal_quality(pcm, 48000)['flags'], ['FLAT_EXTREMA'])
            q = json.loads(log.getvalue())
            self.assertEqual(q['flat_top_max_samples'], samples)
            self.assertEqual(q['long_flat_top'], reject)
            self.assertEqual(q['flat_top_runs'], 1)
            pcm.fill(0)

    def test_excessive_amplitude_and_dropout_have_exact_numeric_diagnostics(self):
        for kind, expected in (('peak', 'peak > 10**(3/20)'), ('dropout', 'min_block_rms <= 1e-5')):
            pcm = tone()
            if kind == 'peak':
                pcm[100] = core.MAX_SAMPLE_PEAK + .001
            else:
                pcm[48000:96000] = 0
            with patch('sys.stderr', new_callable=io.StringIO) as log:
                with self.assertRaises(core.Rejected):
                    core.extract(pcm, 48000, 'bad', core.identity(), 'file')
            q = json.loads(log.getvalue())
            self.assertEqual(q['violated_conditions'], [expected])
            self.assertTrue(np.isfinite(q['peak']) and np.isfinite(q['rms']))
            self.assertTrue((pcm == 0).all())

    def test_diagnostics_failure_still_wipes_and_does_not_extract(self):
        pcm = tone()
        pcm[100] = 1.02
        with patch('sys.stderr.write', side_effect=OSError('PRIVATE_SENTINEL')), patch('core.rhythm_pi.extract') as dsp:
            with self.assertRaises(OSError):
                core.extract(pcm, 48000, 'bad', core.identity(), 'file')
            dsp.assert_not_called()
        self.assertTrue((pcm == 0).all())

    def test_current_quality_schema_rejects_forged_metrics_and_policy(self):
        for key, value in (('outside_unit_samples', -1), ('flat_top_runs', True), ('flat_top_fraction', float('nan')),
                           ('flat_top_samples', 1), ('long_flat_top', 'false'), ('policy', 'unknown'),
                           ('flags', ['TRUSTED_MASTER']), ('status', 'CLEAN'), ('peak', 2), ('rms', 3)):
            with self.subTest(key=key):
                row = copy.deepcopy(self.normal)
                row['quality'][key] = value
                with self.assertRaises(core.Rejected):
                    core.validate_record(row)
        row = copy.deepcopy(self.normal)
        row['profile']['feature_schema'] = 'incompatible-v2'
        with self.assertRaises(ValueError):
            core.validate_record(row)

    def test_v1_v2_rows_preserved_v3_upgrade_and_mixed_search_notices(self):
        first = legacy(self.normal)
        old_stream = legacy(self.normal)
        old_stream.update(schema=core.STREAM_SCHEMA, source='yandex_stream', identity=core.stream_identity('123', '123'))
        old_stream['profile'].update(id='yandex-stream-123', recording_group='yandex-stream-123')
        old_stream['capture'] = dict(method='authorized-yandex-stream-ffmpeg', sample_rate=48000, codec='mp3',
            bitrate_kbps=192, start_seconds=30, seconds=12, received_bytes=100000,
            metadata=dict(id='123', title='', artists=[], duration_seconds=90, album_id=None, album_title=''),
            extractor_schema=core.retrieval.FEATURE_SCHEMA, started_at=old_stream['observed_at'], stopped_at=old_stream['observed_at'])
        with tempfile.TemporaryDirectory(dir='/tmp') as temp:
            index = core.Index(Path(temp) / 'index')
            index.put(first); index.put(old_stream)
            with index.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
                before = db.execute('SELECT * FROM records ORDER BY id').fetchall()
            pcm = tone(); pcm[100] = 1.02
            with patch('sys.stderr', new_callable=io.StringIO):
                current = core.extract(pcm, 48000, 'current', core.identity(), 'file')
            index.put(current)
            self.assertEqual(index.put(old_stream), 'UNCHANGED')
            with index.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
                after = db.execute("SELECT * FROM records WHERE id != 'current' ORDER BY id").fetchall()
            self.assertEqual(before, after)
            expected = core.retrieval.search('normal', [r['profile'] for r in index.records()], top=2, profile='acoustic')
            actual = index.search('normal', 2)
            self.assertEqual(actual.pop('query_signal_quality')['status'], 'LEGACY_ACCEPTED')
            for result in actual['results']:
                notice = result.pop('signal_quality')
                if result['id'] == 'current':
                    self.assertIn('SAMPLE_OVERSHOOT', notice['flags'])
            self.assertEqual(actual, expected)
            another_legacy = copy.deepcopy(first)
            another_legacy['profile'].update(id='legacy-later', recording_group='legacy-later')
            index.put(another_legacy)
            with index.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
            with patch('sys.argv', ['personal_index', '--list', '--index-dir', str(index.path.parent)]), \
                    patch('sys.stdout', new_callable=io.StringIO) as log:
                personal_index.main()
            self.assertIn('SAMPLE_OVERSHOOT', log.getvalue())
            self.assertIn('LEGACY_ACCEPTED', log.getvalue())

    def test_rejected_stream_never_creates_index(self):
        pcm = np.clip(tone(level=2), -1, 1)
        capture = dict(started_at='2026-10-16T00:00:00+00:00', metadata=dict(id='123', title='PRIVATE', artists=[]))
        with tempfile.TemporaryDirectory(dir='/tmp') as temp, patch('yandex_stream.acquire', return_value=(pcm, capture)), \
                patch('sys.argv', ['personal_index', '--yandex-stream', '--track-id', '123', '--index-dir', temp + '/index']), \
                patch('sys.stderr', new_callable=io.StringIO) as log:
            with self.assertRaisesRegex(core.Rejected, 'FLAT_TOP_CLIPPING_SUSPECTED'):
                personal_index.main()
            self.assertEqual(list(Path(temp).iterdir()), [])
            self.assertNotIn('PRIVATE', log.getvalue())
        self.assertTrue((pcm == 0).all())


if __name__ == '__main__':
    unittest.main()
