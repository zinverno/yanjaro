# Agent task: Acoustic Lab v0.1 (separate experimental PR)

Use existing repo https://github.com/zinverno/yanjaro, `main` after published v0.2.0rc4. Do not rewrite or tag the published release. Read current `yanjaro/recommend.py`, `docs/EXPERIMENT.md`, and `pyproject.toml` first.

1. Create a new branch from CURRENT main, e.g. `experiment/acoustic-lab-v01`. Do not touch files in `yanjaro/`, main package dependencies, runtime player, packaging or release workflows.
2. Place the `experiments/acoustic` directory from this archive into the repository. Its CLI analyzes authorized local audio only, records explicit session feedback, trains a nonnegative pairwise logistic ranker using NumPy, and compares held-out session ranking accuracy vs a fixed rhythm-first baseline.
3. Install dependencies in a separate Python venv; no system Python or system package mutations. Run `python -m unittest discover -s tests -v` from within `experiments/acoustic` and check `--help`. Fix any version/platform compatibility issues without changing the published Yanjaro runtime.
4. Verify synthetic audio extraction and session-local train/eval separately. Cover audio absence, silence, malformed ID and missing files, schema mismatch, fewer than six sessions, duplicate feedback, safe atomic storage, no network usage, reproducibility, and no data from Yandex SDK. Record PASS/FAIL/NOT RUN. Test 10–20 local tracks only after OWNER chooses legally permitted audio and authorizes indexing; do not ask for account token or Yandex audio.
5. Review model limitations and potential leakage: splits must be by session, context defined by seeds BEFORE ratings, not generated from target labels; provide a readable validation report. Never report untrained baseline as ML and never label an implicit skip as a negative example.
6. Open a **draft PR** describing model design, generated synthetic tests and missing real data. No merge, release, tag, AUR, cloud upload or automatic Yanjaro integration without permission.
7. After the user has enough real session labels, compare ranker with baseline and (if personally evaluated) the existing Yanjaro shuffle/experiment in a controlled user study before designing UI integration. Preserve opt-in privacy.

This prototype is intentionally a first working research scaffold, not a finished acoustic foundation or an audio manipulation / remix engine.
