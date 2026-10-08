"""Credential-free guards for the clean-container input boundary; no Docker required."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare_clean', Path(__file__).with_name('prepare-clean.py'))
prepare_clean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_clean)


class CleanInputs(unittest.TestCase):
    def test_fresh_checkout_exports_pinned_trees_and_verifiable_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'input'
            inputs = prepare_clean.prepare(out)
            for name in ('candidate', 'previous'):
                with tarfile.open(out / (name + '.git.tar')) as archive:
                    names = archive.getnames()
                    self.assertIn('scripts/prepare-native.py', names)
                    self.assertIn('tests/test_api.py', names)
                    self.assertFalse(any(p.startswith(('dist/', '.git/', '.venv/')) for p in names))
                self.assertEqual(len(inputs[name]['source_commit']), 40)
            for line in (out / 'SHA256SUMS').read_text().splitlines():
                digest, name = line.split('  ')
                self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), digest)
            with self.assertRaises(FileExistsError):
                prepare_clean.prepare(out)

    def test_candidate_manifest_mismatch_fails_before_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'packaging').mkdir()
            for name in ('clean-inputs.json', 'candidate-rc2-3.json'):
                (root / 'packaging' / name).write_bytes((prepare_clean.ROOT / 'packaging' / name).read_bytes())
            p = root / 'packaging/clean-inputs.json'
            inputs = json.loads(p.read_text())
            inputs['candidate']['source_sha256'] = '0' * 64
            p.write_text(json.dumps(inputs))
            with patch.object(prepare_clean, 'ROOT', root), self.assertRaises(AssertionError):
                prepare_clean.prepare(root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_floating_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'packaging').mkdir()
            for name in ('clean-inputs.json', 'candidate-rc2-3.json'):
                data = json.loads((prepare_clean.ROOT / 'packaging' / name).read_text())
                if name == 'clean-inputs.json':
                    data['candidate']['source_commit'] = 'HEAD'
                else:
                    data['source_commit'] = 'HEAD'
                (root / 'packaging' / name).write_text(json.dumps(data))
            with patch.object(prepare_clean, 'ROOT', root), self.assertRaisesRegex(AssertionError, 'full Git commit'):
                prepare_clean.prepare(root / 'output')


if __name__ == '__main__':
    unittest.main()
