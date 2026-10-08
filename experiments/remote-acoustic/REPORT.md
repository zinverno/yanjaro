# Remote acoustic experiment report — 2026-10-08

Base: `zinverno/yanjaro` main `1c83c3776de565ed57416015f32a7ddd999af29f`.
Branch: `experiment/remote-acoustic-yambda`. Draft/unmerged; published `v0.2.0rc4`, production manifests, player, Release and AUR are outside this diff. No Render deployment.

## Real-data evidence

Pinned dataset: [`yandex/yambda@dd6f3a19eef5866e346c3270e098baa641a44948`](https://huggingface.co/datasets/yandex/yambda/tree/dd6f3a19eef5866e346c3270e098baa641a44948).

| Check | Result |
|---|---|
| Parquet metadata and bounded range reads | PASS: HTTP 206; 123,424,184 bytes read, below 128 MiB |
| Embedding table | 7,721,749 rows, 30 row groups, 13,814,230,943-byte full object |
| Actual schema | `item_id: uint32`; `embed` and `normalized_embed`: `large_list<double>` |
| Actual normalized vectors | 256 decoded sample rows, dimension 128, finite; norm range 0.9999999999999998–1.0000000000000007 |
| Feedback input | 881,456 likes (7,180,817 bytes), 107,776 dislikes (990,007 bytes); uint32 uid/timestamp/item_id, uint8 is_organic |
| Historical pair preparation | PASS: 45,565 pairs, 67,418 required IDs, 4,376 users; context precedes both targets and excludes them |
| User-disjoint split before audio matching | Train: 35,741 pairs / 3,476 users; holdout: 9,824 pairs / 900 users |
| Audio coverage from sampled group 29 | 1,018 required IDs; **0 complete pairs**, 45,565 missing |
| Real training, cosine/learned holdout accuracy, weights | **NOT RUN / unavailable**: probe coverage is insufficient |
| HfFileSystem in this environment | BLOCKED: `ConnectError`; no full-download fallback |
| Integrated strict-range CLI on hosted runner / Colab | NOT RUN |

Machine-readable [range/schema report](reports/real-data-probe.json) and [feedback preparation report](reports/real-feedback-prepare.json) contain file/range hashes and aggregate counts, never user IDs or vectors. Small feedback files were downloaded with explicit size/time limits, then the actual `read_events` and `build_pairs` functions were run. This is local real-data preparation, not a claimed remote `prepare` execution.

The range probe downloaded the footer (8 + 10,403 bytes), last-group IDs (480,216 bytes) and last-group normalized vectors (122,933,557 bytes). Arrow decoded a sparse local assembly of only those ranges; the full 13.8 GB object was never downloaded. All 119,573 rows in that already downloaded group were subsequently checked for required-ID coverage without more network traffic. Total feedback plus embedding payload: 131,595,008 bytes, excluding small metadata APIs/data card and source/dependency retrieval.

## Resource decision

Only `item_id` and `normalized_embed` are needed. Their compressed full-table projection is **7,969,776,991 bytes (7.42 GiB)** plus metadata requests. This avoids reading the unused `embed` column, not a guarantee of cheap full training.

The 122,933,557-byte vector range took 61.997 seconds. Extrapolation gives ~67 minutes for projected payload; 50% headroom gives ~100 minutes. This is a single local observation, **not a measured GitHub runner duration**. It exceeds the configured 3600-second extraction gate, so no full pass was attempted.

Measured peak RSS: ~196 MiB for sparse sample decoding, ~238 MiB for feedback preparation. Strict HTTP buffering on a hosted runner is not included in those local measurements. Largest projected group is about 270 MB compressed; HTTP buffering can temporarily hold multiple copies. Selected 67,418 vectors × 128 × float32 have ~33 MiB raw payload; pair features need ~45 MiB at float64, plus dictionaries, temporary arrays and Arrow buffers. A 6 GiB process address-space limit and 1 GiB free-disk preflight leave room without storing the full table. No GPU is required for the 128-weight diagonal optimizer.

[GitHub's public standard Linux runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) is documented as 4 CPU / 16 GB RAM / 14 GB SSD. Public standard-runner use is free; private repositories use account minutes. The repository is public, but actual runner throughput and limits have not been measured. The workflow enforces a fresh probe, byte/time/memory limits and an 85-minute job timeout. No automatic retries or synthetic substitutes.

## Integration and validation

- Imported the standalone project into `experiments/remote-acoustic/`; root training workflow installs from this subdirectory. The live player and existing distribution workflow are unchanged.
- Fixed the extra-batch read at `max_batches`, added strict HTTP response/byte/deadline checks, fixed source provenance and stale-artifact handling, and recorded split user counts plus separate metrics.
- Probe is the default manual mode. A bounded training attempt may fail on missing context vectors; a full attempt must pass the resource preflight. Failure is preserved as failure, with aggregate reports.
- Tests: 20 passed locally, including all data/model tests, strict-range regression tests and server startup rejection. Fixtures are synthetic and are not model-quality evidence.
- Three synchronous TestClient HTTP tests could not complete locally: even the original first `/healthz` test hung in the AnyIO blocking portal; the diagnostic run was terminated at 40 seconds. API source is unchanged. These tests remain required by the workflow (120-second suite timeout); they were not weakened or skipped there.
- Notebook: PASS for JSON/cell structure and Python syntax (12 cells); Colab execution NOT RUN. Workflow YAML parsed, manual-only event and read-only contents permissions checked; hosted execution NOT RUN.
- PyArrow upper bound widened from `<24` to `<26` to include the available/tested 25.0.1. Local environment: Python 3.12.13, NumPy 2.2.6, PyArrow 25.0.1, pytest 9.1.1, FastAPI 0.141.1, Starlette 1.7.0, HTTPX 0.28.1. An isolated temporary venv was used; system Python was not changed.

## Next gate

[GitHub requires the dispatch workflow on the default branch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow). Only the existing clean-distribution workflow is registered on `main`; this experimental training path returned 404 before publication. No merge or default-branch change is authorized in this handoff.

The next owner decision is to register the reviewed manual workflow on `main` separately, then run `mode=probe` against the experimental ref. Only a successful remote probe/resource gate can precede a real training attempt. Save successful `model.json` and `metrics.json` from its artifact, compare holdout accuracy honestly, and review the weights before the separate Render stage. Missing weights currently block that stage.
