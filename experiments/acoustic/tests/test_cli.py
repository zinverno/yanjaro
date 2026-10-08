import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from acoustic_lab.cli import main
from acoustic_lab.core import write_json
from test_core import fake_lib


class CliTests(unittest.TestCase):
    def test_cli_train_and_rank_without_yandex_network(self):
        with tempfile.TemporaryDirectory() as td:
            work=Path(td)
            write_json(work/'library.json',fake_lib())
            cases=[('slow','slow-good','slow-bad'),('medium','mid-good','mid-bad'),
                   ('fast','fast-good','fast-bad')]*3
            with contextlib.redirect_stdout(io.StringIO()):
                for i,(seed,good,bad) in enumerate(cases):
                    id=f'context-{i}'
                    self.assertEqual(main(['--workspace',td,'new-session',id,seed]),0)
                    self.assertEqual(main(['--workspace',td,'rate',id,good,'yes']),0)
                    self.assertEqual(main(['--workspace',td,'rate',id,bad,'no']),0)
                self.assertEqual(main(['--workspace',td,'train']),0)
                self.assertEqual(main(['--workspace',td,'recommend','context-0','--limit','3']),0)
            model=json.loads((work/'model.json').read_text())
            self.assertEqual(model['training']['holdout_sessions'],3)
            self.assertGreaterEqual(model['training']['holdout_pairs'],3)


if __name__=='__main__':
    unittest.main()
