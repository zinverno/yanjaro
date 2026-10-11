"""The runtime fix must not enable or reauthorize the consumed experiment."""
from pathlib import Path
import re
import unittest

from acoustic_similarity.cap2 import BASE_HEAD, RUN_NUMBER

ROOT = Path(__file__).parents[1]
SETUP = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"


class RuntimeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = (ROOT.parents[1] / ".github/workflows/acoustic-similarity.yml").read_text()
        cls.jobs = dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow,
                                   flags=re.M | re.S))

    def test_same_pinned_runtime_in_smoke_tests_and_disabled_cap2(self):
        for name in ("tests", "runtime-smoke", "cap2-pilot"):
            block = self.jobs[name]
            self.assertIn(SETUP, block)
            self.assertIn("python-version: '3.12.13'", block)
            self.assertNotIn("RUNNER_TOOL_CACHE", block)
            self.assertLess(block.index(SETUP), block.index("-r requirements.lock"))

    def test_smoke_has_install_checks_tests_and_only_help_cli(self):
        block = self.jobs["runtime-smoke"]
        for check in ("sys.version_info[:3] == (3, 12, 13)", "python -m pip --version",
                      "pip --version", "--require-hashes --only-binary=:all:", "--no-index --no-deps",
                      "python -m pip check", "import acoustic_similarity", "python scripts/runtime_smoke.py",
                      "yanjaro-similarity --help", "yanjaro-rhythm --help", "acoustic_similarity.cap2 --help"):
            self.assertIn(check, block)
        self.assertNotIn("needs:", block)
        self.assertNotRegex(block, r"acoustic_similarity\.(cap2|rhythm) run\b")
        self.assertNotIn("datasets/", block)

    def test_training_disabled_and_historical_guards_unchanged(self):
        for name in ("cap2-pilot", "groove-pilot"):
            self.assertIn("if: ${{ false }}", self.jobs[name])
        self.assertEqual(RUN_NUMBER, "5")
        self.assertEqual(BASE_HEAD, "15e911d829a6f3683129de2bfcac37e47f55e995")
        self.assertIn(BASE_HEAD, self.jobs["cap2-pilot"])


if __name__ == "__main__":
    unittest.main()
