# Technical validation — 2026-11-13

Real new-track indexing, concrete real-audio trial selection, listening and human
analysis: **NOT RUN**. No owner consent was solicited or supplied for real indexing.
No real audio was acquired, decoded, indexed, transmitted or published in this task.
No model fitting, weight change, GPU or paid provider call.

## Local checks

Python **3.12.13**, all **27** packages installed with the existing hash-locked
`acoustic-similarity/requirements.lock`; `uv pip check` passes. PyPI DNS was
unavailable. Installation ultimately succeeded **offline** from copies of existing
cached wheels and their hash metadata in a disposable `/tmp` cache/environment.
No shared environment or lock file was modified.

| Check | Observed result |
|---|---|
| v2 Python tests | **19 PASS** |
| Original frozen pilot Python tests | **10 PASS** |
| Original Acoustic Retrieval tests | **12 PASS** |
| v2 Node UI/transport tests | **PASS**, including final question 12, five choices, export/restore, conflict and withdrawal |
| Original pilot Node contract and UI suites | **2 PASS** |
| Locked dependency compatibility | **PASS**, 27 packages |
| Source pins / original frozen selection | **PASS** |
| Browser startup | **BLOCKED**, before loading the study |
| Audible playback, physical device, real listeners | **NOT RUN** |

The 19 tests cover strict admission/rights/novelty, consent refusal before decoding,
create-only/private output, unchanged ranker outputs, missing coverage/tie/abstention,
quota failure, exact case counts, input-order invariance, complementary balanced
schedules, and repeat separation over 100 deterministic case-ID sets. They also test
one actual generated 15-second waveform through both frozen extractors and native
float32 WAV reconstruction, reject overshoots, verify seals and blind projection,
validate responses/CSV, require closeout, and check analysis denominators and A/B
decoding across listeners.

The package-orchestration fixture substitutes synthetic descriptor rows explicitly;
it is not evidence that a real 12–16-song pool will meet selection quotas. Response
and completed-analysis tests use **in-memory enum fixtures only**; disk response
fixtures are tagged `technical-test-only`, and the analyzer rejects them. No human
response files or pretend musical judgments were created. This is technical
validation, not perceived similarity evidence.

Chromium was attempted with a disposable profile and exited 133 at startup:
`crashpad/util/linux/socket.cc:45: setsockopt: Operation not permitted (1)`.
No page, screenshot, browser playback, actual localStorage or browser network trace
was verified in that attempt. Node DOM adapters verify handlers and transport;
libsndfile verifies native samples; neither establishes browser/audio-device success.
The owner must check first opening and playback before answering.

## Reproduction and boundaries

Commands are in [README.md](README.md). The new dedicated CI workflow runs only
synthetic/contract checks, with read-only repository permissions and the same locked
dependencies. It does not run `prepare`, collect audio or upload artifacts. Its
status belongs to the exact PR head; consult the PR checks for current hosted results.

The new branch starts at PR #11 commit
`a9fe148cc9b81fcfb76d55ea11d18b701bbd0e84`. The diff adds only this experiment folder
and `.github/workflows/blind-acoustic-evaluation-v2.yml`. The existing pilot,
Acoustic v1, corrected PI, coefficients, player, lock files and old workflows are
unchanged. PR #10/#11/#12/#13, main, releases and deployment remain outside this PR.

No claims of population accuracy, retrieval quality or model improvement follow
from these tests. The future real run is still gated by an owner-filled permitted
pool, fresh local consent, successful freeze, independent listening and closeout.
