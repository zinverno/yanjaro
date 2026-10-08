# Yanjaro Remote Acoustic Ranker — research experiment

Standalone import of `yanjaro-remote-acoustic-v01.zip`, isolated from the published player. See [REPORT.md](REPORT.md) for measured real-data evidence and [STATUS.md](STATUS.md) for acceptance gates. No real trained weights are present yet.

This learns a diagonal ranking metric over **Yambda's 128-dimensional audio embeddings** using explicit like/dislike pairs. Earlier likes are a preference proxy, **not verified mood labels**. The [dataset card](https://huggingface.co/datasets/yandex/yambda) states research-only use. Its anonymized item IDs have no established mapping to Yandex Music track IDs; these vectors are incompatible with the acoustic lab's 27 handcrafted features.

## Manual GitHub Actions

The repository-root [.github/workflows/yanjaro-remote-train.yml](../../.github/workflows/yanjaro-remote-train.yml) is the only workflow for this experiment. It has only `workflow_dispatch`, read-only repository permission, a single-job concurrency group, an 85-minute job timeout and a 6 GiB process address-space limit for data processing. No push/PR-triggered training, deployment, release or package publication.

**Activation gate:** GitHub requires a new dispatch workflow on the default branch. This draft PR does not merge it. After a separately approved registration on `main`, run it with the experiment ref:

```sh
gh workflow run yanjaro-remote-train.yml -R zinverno/yanjaro \
  --ref experiment/remote-acoustic-yambda -f mode=probe
```

- `probe` (default): a fresh real-data range/schema check, at most 128 MiB payload and a 180-second I/O deadline (4-minute process timeout).
- `train-bounded`: fresh probe, small feedback files, then at most 64 batches / 512 MiB by default. Complete matched examples are required; insufficient coverage fails without a model.
- `train-full`: explicit selection plus an adequate byte budget, up to 8192 MiB. A fresh probe must estimate that the projected scan fits the byte limit and 3600 seconds **with 50% time headroom**. The byte and time limits remain enforced during extraction. Observed local probe speed does not meet this full-scan time gate.

`max_read_mib` choices: 512, 1024, 4096, 8192. Probe and small feedback-file traffic are additional to the scan budget. Each feedback file is capped at 32 MiB and 120 seconds. Public standard runners are documented as 4 CPU / 16 GB RAM / 14 GB SSD; available resources and throughput must be checked in the actual run. Private repositories consume plan minutes. This workflow requests neither larger runners nor GPUs.

Only aggregate diagnostics, environment versions, successful real weights and held-out metrics are uploaded. No raw events, IDs or vectors. Reports retain 14 days; successful model/metrics retain 30 days. Download and checksum them after a successful run; they are not permanent storage or a Release.

## Pipeline and bounds

Dataset revision is fixed at `dd6f3a19eef5866e346c3270e098baa641a44948` for all three Parquets. The real schemas are recorded under [reports/](reports/).

`--max-batches` limits decoded batches, **not network bytes**: the first batch can require a whole Parquet column chunk. The imported HfFileSystem implementation did not enforce response status or total traffic; local HfFileSystem probing also failed with `ConnectError`. The integrated reader uses Python's standard-library HTTP range transport with no read-ahead or retries. It checks `206` and exact `Content-Range` before reading a body, rejects unbounded/over-budget reads, and never falls back to downloading the whole object. HTTP range support was measured using bounded curl requests; the integrated transport still needs remote acceptance.

```sh
cd experiments/remote-acoustic
python -m venv .venv
.venv/bin/python -m pip install '.[train,serve,test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/validate_notebook.py
.venv/bin/python -m remote_acoustic.cli probe
# On a remote runtime after reviewing the probe:
.venv/bin/python -m remote_acoustic.cli prepare --work work
.venv/bin/python -m remote_acoustic.cli extract --work work \
  --max-batches 64 --max-read-mib 512 --max-seconds 600
.venv/bin/python -m remote_acoustic.cli train --work work --output artifacts/model.json
```

The [Colab notebook](notebooks/train_in_colab.ipynb) uses checked subprocesses and bounded extraction. Structure/Python syntax validation is distinct from executing it on Colab.

Training requires matching pinned-source receipts and SHA-256 hashes of pairs/vectors. Local arbitrary inputs cannot be automatically labeled `yandex/yambda`. Receipts protect against accidental stale/mixed inputs, not maliciously forged provenance. Failed extraction removes old vector output; a new fit removes stale model/metrics before checking data. Fewer than 100 covered pairs, 20 training pairs or 8 holdout pairs fails the fit.

The stable user-hash split is 80/20, context precedes both targets and excludes them, and only training users enter gradients. Fixed 250 epochs, learning rate 0.035 and L2 0.015; no checkpoint/threshold tuning on holdout. `model.json` and `metrics.json` include source revision, checksums, run/code identity on Actions, pair/user counts, missing coverage, and cosine versus learned accuracy on identical examples. A worse learned result is preserved and reported as such. A partial scan is labeled with its rows/coverage and never implies catalogue coverage.

## Player adapter and deployment gate

[The player's experiment](../../docs/EXPERIMENT.md) uses its existing opt-in local collection/feedback rules. It has no owner for these embeddings or anonymous IDs. A future explicitly invoked adapter must supply lawful candidates in the **same** embedding space and a verified ID mapping. Reject 27-feature vectors at the schema boundary; a separately trained/validated transformation would be a new task. No user account events or Yandex tokens are used here.

`service.py`, `Dockerfile` and `render.yaml` are preserved from the supplied prototype for later review. No API deployment or separate deployment repository is part of this stage. API code requires a real-source model and a secret. Local synthetic tests establish plumbing only:

```sh
python scripts/synthetic_smoke.py  # tagged synthetic-test-only, never a real-data result
```
