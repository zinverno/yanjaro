"""Numerics, immutable provenance, and grouping boundaries; no dataset network access."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from acoustic_similarity.diagnostics import (ARTIFACT_SHA, ablation_weights, boundary_probe, components,
    development_only, load_archive, performer_folds)
from acoustic_similarity.model import contrastive_objective, fit_head, softmax
from acoustic_similarity.rhythm import contrastive_arrays
from test_rhythm import dataset_fixture

ROOT = Path(__file__).parents[1]


class OptimizerNumericsTests(unittest.TestCase):
    def test_gradient_with_offsets_and_regularizer_by_finite_differences(self):
        rng = np.random.default_rng(17)
        X, offset = rng.normal(size=(11, 7)), rng.normal(size=11)
        for theta in (np.zeros(7), np.linspace(-2, 2, 7)):
            for reg in (0., .01, 1.):
                _, gradient = contrastive_objective(theta, X, offset, reg)
                numeric = []
                for i in range(7):
                    delta = np.eye(7)[i]*1e-6
                    numeric.append((contrastive_objective(theta+delta, X, offset, reg)[0]-
                                    contrastive_objective(theta-delta, X, offset, reg)[0])/2e-6)
                np.testing.assert_allclose(gradient, numeric, atol=2e-8, rtol=1e-6)

    def test_loss_sign_moves_towards_positive_and_away_from_negative(self):
        # Coordinate 0 makes the independently closer item closer; coordinate 1 reverses it.
        X = np.array([[-.8, .8], [-.5, .4]])
        w, loss = fit_head(X, np.zeros(2))
        self.assertGreater(w[0], w[1])
        self.assertTrue((X @ w < 0).all())
        self.assertLess(loss, contrastive_objective(np.zeros(2), X, np.zeros(2), 0)[0])

    def test_softmax_stable_and_shift_invariant(self):
        x = np.array([-1000., 0., 1000.])
        np.testing.assert_array_equal(softmax(x), softmax(x+10000))
        self.assertTrue(np.isfinite(softmax(x)).all())
        self.assertEqual(softmax(x).sum(), 1.)

    def test_concentration_bound_is_enforced_in_logit_space(self):
        trace = []
        w, _ = fit_head(np.tile([-1., 1., .5], (8, 1)), np.zeros(8),
                        logit_bound=np.log(2)/2, trace=trace)
        self.assertLessEqual(max(w)/min(w), 2+1e-12)
        self.assertLessEqual(np.max(np.abs(trace)), np.log(2)/2)
        self.assertTrue(any(np.isclose(np.abs(trace[-1]), np.log(2)/2)))

    def test_invalid_optimizer_settings_rejected(self):
        for config in ({"lr": 0}, {"regularization": -1}, {"logit_bound": 0}, {"epochs": 0}, {"lr": float('nan')}):
            with self.assertRaisesRegex(ValueError, "settings"):
                fit_head([[-1, 1]], [0], **config)


class DiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dev, cls.weights, cls.integrity, _, _ = load_archive(ROOT / "validation/groove-cpu-v1/artifacts.zip")

    def test_archive_provenance_and_reproduction(self):
        self.assertEqual(self.integrity['archive_sha256'], ARTIFACT_SHA)
        self.assertEqual(self.integrity['members_sha256']['model.json'],
                         '9cfa22a9adc22b6990d3a01200a4d9d5fe2dcba469ea97fe45b5bfcff7a9b147')
        X, _ = contrastive_arrays(self.dev, 'train')
        np.testing.assert_allclose(fit_head(X, np.zeros(len(X)))[0], self.weights, atol=1e-12, rtol=0)
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'changed archive'); f.flush()
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                load_archive(f.name)

    def test_old_test_and_validation_cannot_enter_cv_training(self):
        dataset = dataset_fixture()
        before = development_only(dataset)
        for r in dataset['rows']:
            if r['split'] == 'test':
                r['features'] = [float('nan')]; r['target'] = None
        self.assertEqual(before, development_only(dataset))
        self.assertEqual({r['split'] for r in self.dev['rows']}, {'train', 'validation'})
        X, trips = contrastive_arrays(self.dev, 'train')
        lookup = {r['id']: r for r in self.dev['rows']}
        for drummer, mask, _ in performer_folds(self.dev):
            for t, held in zip(trips, mask):
                for key in ('anchor','positive','negative'):
                    self.assertEqual(lookup[t[key]]['split'], 'train')
                    self.assertEqual(lookup[t[key]]['drummer'] == drummer, held)
        altered = copy.deepcopy(self.dev)
        for r in altered['rows']:
            if r['split'] == 'validation': r['features'] = [999]*128
        np.testing.assert_array_equal(contrastive_arrays(altered, 'train')[0], X)

    def test_connected_triplet_or_duplicate_source_cannot_cross_performer_fold(self):
        for change in ('triplet', 'source'):
            dev = copy.deepcopy(self.dev)
            rows = [r for r in dev['rows'] if r['split'] == 'train']
            a = rows[0]; b = next(r for r in rows if r['drummer'] != a['drummer'])
            if change == 'triplet':
                dev['triplets'].append({'anchor': a['id'], 'positive': b['id'], 'negative': rows[1]['id'], 'split': 'train'})
            else:
                b['audio_sha256'] = a['audio_sha256']
            with self.assertRaises(ValueError): list(performer_folds(dev))

    def test_distance_symmetry_self_distance_and_block_normalization(self):
        f = np.array([r['features'] for r in self.dev['rows']])
        np.testing.assert_allclose(np.linalg.norm(f[:, :64].reshape(-1,4,16), axis=2), 1, atol=1e-12)
        a, b = f[:2]
        self.assertEqual(float((a-b)**2 @ self.weights), float((b-a)**2 @ self.weights))
        self.assertEqual(float((a-a)**2 @ self.weights), 0.)
        self.assertTrue((self.weights > 0).all())

    def test_next_run_is_unapproved_independent_and_exactly_budgeted(self):
        proposal = json.loads((ROOT/'validation/groove-diagnostics-v1/next-run-proposal.json').read_text())
        self.assertTrue(proposal['approval_required'])
        self.assertIn('NOT RUN', proposal['status'])
        old = json.loads((ROOT/'datasets/groove-cohort.json').read_text())
        new = proposal['new_test']['records']
        self.assertFalse({r['metadata']['drummer'] for r in old['records']} & {r['metadata']['drummer'] for r in new})
        self.assertEqual({r['metadata']['bpm'] for r in new}, {'88'})
        budget = proposal['budget']
        audio = sum(r['compressed_bytes']+r['local_header_read_bytes']+r['member_name_read_bytes'] for r in new)
        self.assertEqual(audio, budget['new_audio_http_body_bytes'])
        source = audio + proposal['sources']['midi_bytes'] + proposal['sources']['directory_bytes']
        self.assertEqual(source, budget['total_source_http_body_bytes'])
        self.assertLess(source+budget['saved_training_artifact_transfer_bytes']+budget['transport_and_output_reserve_bytes'],
                        budget['authorized_limit_if_approved_bytes'])
        self.assertIn('if: ${{ false }}', (ROOT.parents[1]/'.github/workflows/acoustic-similarity.yml').read_text())

    def test_boundary_probe_exposes_v1_limitation(self):
        probe = boundary_probe()
        self.assertIn('NOT TRAINING', probe['kind'])
        self.assertEqual(probe['results'][0]['flux_l2'], 0.)
        self.assertGreater(probe['results'][-1]['flux_l2'], 1.)

    def test_ablation_mixtures_keep_uniform_endpoint_and_bound(self):
        # Cap2's only real fit belongs to the explicitly authorized experiment job.
        X, _ = contrastive_arrays(dataset_fixture(), 'train')
        uniform = ablation_weights('uniform', X)
        original = ablation_weights('original', X)
        np.testing.assert_allclose(ablation_weights('mix_0.1', X), .9*uniform+.1*original)
        cap = ablation_weights('cap2', X)
        self.assertLessEqual(cap.max()/cap.min(), 2+1e-12)
        self.assertEqual(set(components(self.dev['rows'], self.dev['triplets'])), {r['id'] for r in self.dev['rows']})


if __name__ == '__main__':
    unittest.main()
