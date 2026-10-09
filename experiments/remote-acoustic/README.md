# Yanjaro Remote Acoustic Ranker — research experiment

Standalone import of `yanjaro-remote-acoustic-v01.zip`, isolated from the published player. See [REPORT.md](REPORT.md) for measured real-data evidence and [STATUS.md](STATUS.md) for acceptance gates. No real trained weights are present yet.

This learns a diagonal ranking metric over **Yambda's 128-dimensional audio embeddings** using explicit like/dislike pairs. Earlier likes are a preference proxy, **not verified mood labels**. The [dataset card](https://huggingface.co/datasets/yandex/yambda) states research-only use. Its anonymized item IDs have no established mapping to Yandex Music track IDs; these vectors are incompatible with the acoustic lab's 27 handcrafted features.

## Manual GitHub Actions

The repository-root [.github/workflows/yanjaro-remote-train.yml](../../.github/workflows/yanjaro-remote-train.yml) is now **probe-only**. [Registration PR #8](https://github.com/zinverno/yanjaro/pull/8) adds only that same file to main; it must not be merged without owner approval. PR #7 remains separate and draft.

After approval and merge of registration PR #8 only, the exact command is:

```sh
gh workflow run yanjaro-remote-train.yml \
  --repo zinverno/yanjaro \
  --ref experiment/remote-acoustic-yambda \
  -f mode=probe
```

The workflow has only `workflow_dispatch` and `contents: read`. An executed shell guard accepts only `probe` and the exact experimental ref. Inputs pass through quoted environment variables; actions are pinned to full SHAs and checkout does not retain credentials. There is no training mode, dataset preparation, full scan, deployment or release step. A run on main intentionally fails before checkout because the Python experiment is not on main.

Unchanged probe limits: 128 MiB payload, 180-second I/O deadline, 4-minute process timeout, 6 GiB process address space. The job limit is reduced to 10 minutes. Only aggregate `probe.json` is uploaded, retained for 14 days. Registration is not hosted probe acceptance; no probe has been dispatched during the follow-up.

[Remote acoustic experiment tests](../../.github/workflows/remote-acoustic-tests.yml) runs all tests and notebook syntax/structure checks for PRs touching this experiment or its workflows. These automatic checks use synthetic fixtures, with no Yambda downloads or real training. The existing Arch/Manjaro workflow remains separate.

## Pipeline and bounds

Dataset revision is fixed at `dd6f3a19eef5866e346c3270e098baa641a44948` for all three Parquets. The real schemas are recorded under [reports/](reports/).

`--row-groups 29` explicitly selects a physical group without changing byte/time caps. `--max-batches` limits decoded batches, **not network bytes**: the first batch can require a whole Parquet column chunk. The imported HfFileSystem implementation did not enforce response status or total traffic; local HfFileSystem probing also failed with `ConnectError`. The integrated reader uses Python's standard-library HTTP range transport with no read-ahead or retries. It checks `206` and exact `Content-Range` before reading a body, rejects unbounded/over-budget reads, and never falls back to downloading the whole object. HTTP range support was measured using bounded curl requests; the integrated transport still needs remote acceptance.

```sh
cd experiments/remote-acoustic
python -m venv .venv
.venv/bin/python -m pip install '.[train,serve,test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/validate_notebook.py
.venv/bin/python -m remote_acoustic.cli probe
# Future remote work only after approval of the concrete traffic/training budget:
.venv/bin/python -m remote_acoustic.cli prepare --work work
.venv/bin/python -m remote_acoustic.cli extract --work work \
  --max-batches 64 --max-read-mib 512 --max-seconds 600
.venv/bin/python -m remote_acoustic.cli train --work work --output artifacts/model.json
```

`coverage --work work` reads only the ID column under a separate 32 MiB / 180-second cap, using prepared real-pair receipts. It reports aggregate ID availability and structural pair coverage; it cannot validate unread vectors or produce model metrics. The current real analysis found **zero complete pairs for every row-group set fitting 512 MiB**. Do not repeat a partial scan expecting training success. See [REPORT.md](REPORT.md) for exact coverage and conditional scaling options.

The [Colab notebook](notebooks/train_in_colab.ipynb) uses checked subprocesses and bounded extraction. Structure/Python syntax validation is distinct from executing it on Colab.

Training requires matching pinned-source receipts and SHA-256 hashes of pairs/vectors. Local arbitrary inputs cannot be automatically labeled `yandex/yambda`. Receipts protect against accidental stale/mixed inputs, not maliciously forged provenance. The CLI training code is retained for a future approved run, but is not reachable from the registered workflow. Failed extraction removes old vector output; a new fit removes stale model/metrics before checking data. Fewer than 100 covered pairs, 20 training pairs or 8 holdout pairs fails the fit.

The stable user-hash split is 80/20, context precedes both targets and excludes them, and only training users enter gradients. Fixed 250 epochs, learning rate 0.035 and L2 0.015; no checkpoint/threshold tuning on holdout. `model.json` and `metrics.json` include source revision, checksums, run/code identity when run on Actions, pair/user counts, missing coverage, and cosine versus learned accuracy on identical examples. A worse learned result is preserved and reported as such. A partial scan is labeled with its rows/coverage and never implies catalogue coverage.

## Player adapter and deployment gate

[The player's experiment](../../docs/EXPERIMENT.md) uses its existing opt-in local collection/feedback rules. It has no owner for these embeddings or anonymous IDs. A future explicitly invoked adapter must supply lawful candidates in the **same** embedding space and a verified ID mapping. Reject 27-feature vectors at the schema boundary; a separately trained/validated transformation would be a new task. No user account events or Yandex tokens are used here.

`service.py`, `Dockerfile` and `render.yaml` are preserved from the supplied prototype for later review. No API deployment or separate deployment repository is part of this stage. API code requires a real-source model and a secret. Local synthetic tests establish plumbing only:

```sh
python scripts/synthetic_smoke.py  # tagged synthetic-test-only, never a real-data result
```
