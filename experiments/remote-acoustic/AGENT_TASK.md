> Original archive hand-off retained for context. For this branch, current owner scope and REPORT.md govern: bounded probe first; no merge, full-download fallback or Render deployment.

# Agent hand-off: Remote Acoustic Ranker v0.1

Repository: `zinverno/yanjaro`. Base: current main, separate experimental draft PR; do not alter published `v0.2.0rc4`, AUR, user settings, or system Python.

## Objective

- Integrate **this standalone research service** into an experimental subdirectory, e.g. `experiments/remote-acoustic/`, NOT `yanjaro/` runtime.
- Re-run tests and notebook validation, fix integration defects, and open a draft PR. Main player code, production release manifests and AUR packaging must remain unchanged.
- Establish a remote-training job on real `yandex/yambda` data, with clear costs, quota and license caveats. In this stage no Yandex API songs or streams are processed and no user account data is transferred.

## Tasks

1. Read `README.md` and `notebooks/train_in_colab.ipynb`. Check actual HF repository schemas on a remote Colab instance. The Parquet matrix is about 13.8 GB. Verify HfFileSystem range-reading; if it fails, record BLOCKED and ask for an explicit decision before downloading the entire object.
2. For Yambda-50M likes/dislikes, run `prepare`; verify sample counts, temporal context and number of near-time feedback pairs. Retain all Yambda user-event data only in temporary private workspace, never Git.
3. Run full embeddings scan and record matched ID coverage; `--max-batches 100` is only an I/O probe. Proceed to training only with real matched samples. Do not fabricate positive/negative real metrics.
4. Train the metric; report train/holdout user counts, pair counts, missing coverage, baseline and learned holdout accuracy. No tuning on the held-out group. If holdout learned accuracy is lower, report it transparently. Save learned `artifacts/model.json` with provenance.
5. Create a **separate deployment repository** for the remote API only after owner approval. Ensure production API requires a real model and random secret; never bundle 13.8 GB vectors or Yandex tokens.
6. Check `/healthz` and authenticated `/v1/rank` remotely, including 401/422 tests and Render cold-start latency. Do not claim Yanjaro integration until actual feature-to-track mapping is available.
7. Read `docs/EXPERIMENT.md` in Yanjaro to plan an **explicit feature adapter**; 27 handcrafted acoustic features and Yambda embeddings are incompatible without a separately trained transformation. Anonymized Yambda IDs are not real Yandex track IDs.
8. Return PASS / FAIL / NOT RUN, CI links, remote training evidence and next blocker. No merge, tag, Release or AUR edits without approval.

## Hard boundaries

- **95%+ Yandex catalog coverage is NOT solved**. Do not label this as such.
- Real-world mood prediction is NOT verified by offline dislike/like proxies.
- A user who downloads music for personal listening is not automatically granted training/redistribution rights; do not implement scraping/downloads of service streams in this experiment.
- Dataset card says research-only despite Apache-2.0 metadata; review use before commercial release.

Optional: review `workflows/yanjaro-remote-train.yml` and, with user approval, place it in the appropriate GitHub repository root `.github/workflows/`. Keep `workflow_dispatch` manual, upload ONLY weights, and report any HF streaming failure instead of falling back to a synthetic model.
