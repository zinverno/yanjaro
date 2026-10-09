# Remote acoustic blocker report — 2026-10-09

Work continues from PR #7 HEAD `079a9b41c8b194f31783a65d8748573b97bb93dc`, verified before changes. Branch: `experiment/remote-acoustic-yambda`. PR #6/#7 remain draft/unmerged. Registration is isolated in [draft PR #8](https://github.com/zinverno/yanjaro/pull/8), branch `ci/register-acoustic-probe`, based on main `1c83c3776de565ed57416015f32a7ddd999af29f`; it adds **only one workflow file**. No published player, Release, AUR or Render changes.

## Test reliability — PASS

The old first HTTP test reproducibly hung in TestClient's AnyIO blocking portal and was terminated after 20 seconds. A minimal `socket.socketpair().send()` reproduced `PermissionError: EPERM` in this execution environment. CPython's asyncio `_write_to_self()` catches that `OSError`, leaving its selector thread asleep while TestClient waits for a future. This is an environment-dependent wakeup failure, not evidence that ranking computation deadlocked.

All three HTTP test functions and their health/authentication/ranking/schema/duplicate/dimension assertions are preserved. They now use [FastAPI's documented HTTPX AsyncClient + ASGITransport pattern](https://fastapi.tiangolo.com/advanced/async-tests/) in one event loop. The two handlers perform only bounded in-memory work (at most 64 candidates × 2048 coordinates), so they use `async def` without worker-thread dispatch. Model loading remains before normal request handling. No dependency downgrade, socket monkeypatch, policy change, skip, xfail or removed test was used. This is not an API deployment or load-test result.

Full local suite: **40 passed, zero skips**. Notebook: 12 cells, structure and Python syntax PASS; Colab execution NOT RUN. [Initial hosted experiment CI](https://github.com/zinverno/yanjaro/actions/runs/37872201042) passed all 23 then-existing tests at `630bed08243074e3442f71badbf3e0663de2ef68`, on Python 3.12, FastAPI 0.143.0, Starlette 1.7.0, AnyIO 4.15.1, NumPy 2.5.3, PyArrow 25.0.1. The expanded final suite is a required job in the new experiment workflow; check the exact final HEAD run linked in PR #7. Arch/Manjaro PASS at the supplied starting SHA verifies distribution builds only.

New PR CI is limited by paths to this experiment and its workflows. It runs all tests and notebook validation, with a 120-second process timeout and diagnostic traceback at 30 seconds. It does not fetch Yambda, start a hosted probe or train real weights. Root packaging CI is unchanged. [Diagnosis receipt](reports/test-hang-diagnosis.json).

## Real embedding coverage — PASS analysis, FAIL training feasibility at 512 MiB

Dataset remains pinned to [`dd6f3a19eef5866e346c3270e098baa641a44948`](https://huggingface.co/datasets/yandex/yambda/tree/dd6f3a19eef5866e346c3270e098baa641a44948). There are 7,721,749 embedding rows in 30 row groups; uint32 item IDs and 128-dimensional normalized `large_list<double>` vectors. The full object is 13,814,230,943 bytes; the needed ID/vector projection totals 7,969,776,991 bytes.

The original 8.17 MB feedback files were reused and SHA-256 checked. The original pair builder is unchanged: 45,565 strictly historical pairs, context length up to 8, 67,418 required IDs and a fixed user-disjoint split. No shorter context, relabeling or holdout-score tuning was introduced to manufacture coverage.

Only the **item_id column** was fetched for the remaining 29 groups. New payload: **30,530,747 bytes**, capped at 32 MiB; prior group-29 IDs (480,216 bytes) were reused. All new responses had exact HTTP 206 Content-Range and expected byte counts. No new vector chunks were downloaded. Raw chunks/events remain in private temporary files, outside Git and public artifacts.

Found required IDs: **63,998**. Missing from the entire embedding table: **3,420**, making **13,394 pairs structurally impossible** even after a full vector pass. Full-table ID coverage would permit at most **32,171 pairs**: 25,437 train / 6,734 holdout, 3,056 / 800 users. These are **ID-only upper bounds**, before validating actual vector values; they are not fit/evaluation metrics.

Every feasible set under the existing 512 MiB cap was enumerated: 30 single groups and 29 pairs consisting of one ordinary group plus the smaller last group. All **59 sets yield zero structurally complete pairs**. Set selection uses training pair counts only, then byte cost and ordinal tie-breaking; holdout counts are reported afterward.

| Physical prefix | Projected ID/vector payload | Structural pairs: train / holdout | Users: train / holdout |
|---|---:|---:|---:|
| Groups 0–13 | 3,787,898,943 B | 74 / 15 | 43 / 12 |
| Groups 0–14 | 4,058,463,224 B | 100 / 22 | 63 / 16 |
| Groups 0–15 | 4,329,027,506 B | 133 / 30 | 84 / 22 |
| Groups 0–19 | 5,411,284,646 B | 825 / 241 | 356 / 101 |
| All groups | 7,969,776,991 B | 25,437 / 6,734 | 3,056 / 800 |

The extractor now accepts explicit `--row-groups`, rejects invalid/duplicate ordinals and keeps the same byte/time limits. The real group-29 check reused already verified cached ranges: 119,573 rows read, 1,018 matched IDs, dimension 128, **zero additional network bytes**. It validates selected-group extraction, not the integrated transport on GitHub. Tests verify that other groups are not selected and the coverage planner reads no vector column.

Evidence: [complete aggregate coverage curve](reports/real-id-coverage.json), [selected-group extraction](reports/selected-group-extraction.json), [original range probe](reports/real-data-probe.json), [original feedback preparation](reports/real-feedback-prepare.json). The remote `coverage` command has a 32 MiB / 180-second ID-only cap and real-input provenance checks; hosted execution remains NOT RUN.

## Scaling design — proposal only, NOT RUN

A small change with a useful ceiling is sequential row-group tasks in **one remote job**: one pinned revision, one immutable pair/split manifest, one shared cumulative byte/deadline budget, and one temporary vector bank. Each task requests only the chosen group's ID/normalized columns, retains required vectors and checks finite values/dimension. It stops before an over-budget request. Failed work does not produce model weights. A final fit happens once after enough complete real pairs are available; all raw state dies with the worker. Public outputs are aggregate coverage/resource receipts and, only after success, real weights plus holdout metrics.

For cross-job or parallel work, independent jobs cannot train from mostly incomplete per-group examples. A coordinator would assign disjoint group ranges and reserve a **single approved total budget**, including retries and metadata. Joining vectors would require explicitly approved private storage or a private persistent worker, with least-privilege access, matching revision/pair checksums, atomic completion receipts and deletion after the join. No public Actions artifacts or caches may transport IDs, events or vectors. Such storage, credentials, jobs and automatic retries have **not** been provisioned. Splitting a 7.97 GB transfer into many jobs does not reduce its total traffic and is not permission to bypass a total cap.

The first sizing candidate is a fixed prefix 0–14, whose structural ceiling is 122 pairs (100 train / 22 holdout). It requires about 4.06 GB plus a probe, feedback and metadata, **well above the current 512 MiB extraction cap**. At the old local range rate, projected payload time is ~34.1 minutes, ~51.2 minutes with 50% headroom, excluding setup/fit. The 22 holdout pairs from 16 users support only a first pipeline experiment, not a strong quality claim. Vector validation may reduce these counts. This is a conditional sizing option, **not an approved training plan or a runner measurement**.

After owner-approved registration and a successful hosted probe, replace that old rate with the actual runner rate and propose one fixed group set, explicit aggregate bytes/time caps, minimum complete train/holdout counts, failure rules, tested dependency versions and artifact retention. Ask for separate approval before any larger vector budget or training. The previous 60-minute full-scan gate would reject the old ~67-minute full projection (~100 minutes with headroom).

[GitHub documents public standard runners as free](https://docs.github.com/en/actions/reference/runners/github-hosted-runners), currently 4 CPU / 16 GB RAM / 14 GB SSD for ubuntu-24.04. A candidate public standard-runner execution requests no GPU or paid runner; private storage/account-specific charges are unmeasured and not authorized. No claim of an actual bill or hosted throughput is made.

## Workflow review and registration — PASS preparation, NOT RUN merge/probe

The file in PR #8 is byte-identical to the reviewed manual workflow in PR #7. It has only `workflow_dispatch`, `contents: read`, full-SHA action pins and `persist-credentials: false`. The only input is `mode=probe`. A shell guard rejects every other mode, main, tags and arbitrary refs before checkout. Inputs are quoted environment variables, never interpolated into shell source. Unit tests execute rejection of training mode and command-injection payloads. The workflow has no training, feedback preparation, vector-extraction or deployment command.

Limits are unchanged or reduced: 128 MiB probe payload, 180-second I/O deadline, 4-minute probe process timeout, 6 GiB process address space, and a 10-minute whole-job timeout. Upload path is exactly aggregate `artifacts/probe.json` with 14-day retention; no directory glob or raw-data artifact. Automatic PR CI is a separate test-only workflow, not a trigger on this manual workflow.

[GitHub requires default-branch registration](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow). After explicit approval and merge of **PR #8 only**, run:

```sh
gh workflow run yanjaro-remote-train.yml \
  --repo zinverno/yanjaro \
  --ref experiment/remote-acoustic-yambda \
  -f mode=probe
```

Running on main intentionally fails; the implementation remains in draft PR #7. No probe was dispatched during this follow-up. No full vector pass, real fit, weights, held-out accuracy or deployment exists yet. The next decision is registration approval; the real training budget follows measured hosted evidence.
