"""Run existing unit regressions offline; never enter a real experiment."""
from contextlib import ExitStack
import json
import sys
import unittest
from unittest.mock import patch

from acoustic_similarity import cap2


def main():
    blocked = []

    def deny(name):
        blocked.append(name)
        raise RuntimeError("Runtime smoke forbids " + name)

    def audit(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto"):
            deny(event)

    score = cap2.score

    def development_score(dataset, split, weights):
        if split == "test":
            deny("cap2 real test evaluation")
        return score(dataset, split, weights)

    # These are process-local fences, not production API changes. Existing train-only
    # numerical regressions remain intact; no model or test result is published.
    sys.addaudithook(audit)
    with ExitStack() as stack:
        for name in ("groove.acquire", "rhythm.acquire", "rhythm.train_head",
                     "rhythm.evaluate", "cap2.new_audio", "cap2.fit_head"):
            stack.enter_context(patch("acoustic_similarity." + name,
                                      side_effect=lambda *a, _name=name, **kw: deny(_name)))
        stack.enter_context(patch.object(cap2, "score", development_score))
        suite = unittest.defaultTestLoader.discover("tests")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not blocked and result.testsRun > 0
    print(json.dumps({"runtime_unit_smoke": "PASS" if passed else "FAIL",
                      "tests": result.testsRun, "forbidden_calls": blocked,
                      "dataset_download_bytes": 0, "cap2_training": "NOT RUN",
                      "real_test_evaluation": "NOT RUN"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
