"""Pinned runtime and fresh authorization must never revive the historical run."""
from pathlib import Path
import re
import unittest

from acoustic_similarity.cap2 import AUTHORIZATION, BASE_HEAD, OUTPUT, RUN_NUMBER

ROOT = Path(__file__).parents[1]
SETUP = "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"


class RuntimeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = (ROOT.parents[1] / ".github/workflows/acoustic-similarity.yml").read_text()
        cls.jobs = dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow,
                                   flags=re.M | re.S))

    def test_same_pinned_runtime_in_smoke_tests_and_cap2(self):
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

    def test_fresh_one_shot_guards_and_historical_job_disabled(self):
        self.assertIn("if: ${{ false }}", self.jobs["groove-pilot"])
        self.assertEqual(RUN_NUMBER, "9")
        self.assertEqual(BASE_HEAD, "0d8955f1788521f6458a64ceea3ba7db8e09b9ba")
        self.assertEqual(AUTHORIZATION, "cap2-2026-10-14-v2")
        self.assertEqual(OUTPUT, "runs/groove-cap2-v2")
        block = self.jobs["cap2-pilot"]
        self.assertIn(BASE_HEAD, block)
        self.assertIn(AUTHORIZATION, block)
        self.assertTrue('if: ${{ false }}' in block or
                        f'github.run_number == {RUN_NUMBER} && github.run_attempt == 1' in block)


if __name__ == "__main__":
    unittest.main()
