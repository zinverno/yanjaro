"""Cache audits must remain development-only and never refit a model."""
import unittest
from pathlib import Path
from runpy import run_path
from unittest.mock import patch

from acoustic_similarity.diagnostics import development_only

# Script-launched smoke has scripts/, not the checkout root, on sys.path.
analyze_cache = run_path(str(Path(__file__).parents[1]/'scripts/rhythm_v2_audit.py'))['analyze_cache']
from test_rhythm import dataset_fixture


class AuditBoundaryTests(unittest.TestCase):
    def test_test_rows_or_triplets_rejected(self):
        with self.assertRaisesRegex(ValueError,'Held-out'): analyze_cache(dataset_fixture())

    def test_cache_probe_is_labelled_and_never_trains(self):
        with patch('acoustic_similarity.diagnostics.fit_head',side_effect=AssertionError('fit forbidden')):
            report=analyze_cache(development_only(dataset_fixture()))
        self.assertIn('NOT RE-EXTRACTED V2',report['kind'])
        self.assertIn('NOT RUN',report['true_v2_uniform_comparison'])
        self.assertEqual(set(report['splits']),{'train','validation'})


if __name__=='__main__': unittest.main()
