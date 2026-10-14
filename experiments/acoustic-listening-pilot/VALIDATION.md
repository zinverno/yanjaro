# Local pilot validation

The ten permitted recordings were used to build two private offline listening
packages. No participant was recruited and no human judgment was generated.
Only source, templates, organizer selection and numeric receipts enter this PR;
audio and response files remain outside the checkout.

| Gate | Result | Evidence |
|---|---|---|
| Initial PR #10 HEAD / clean checkout | PASS | `35aecde3311fa302e0ac1548d9c53f336ed9c928` |
| Audio + evidence hashes | PASS | All ten originals and ten snapshots; pinned manifest |
| Historical windows | PASS | Native sample boundaries and prior mono waveform SHA-256, 15 s each |
| Case selection | PASS | 12 unique cases, six categories × 2, ten distinct anchors; seed 2026101401 |
| Blinding / stimulus mapping | PASS, static/local decode | 84 role mappings across two pages; metadata-free WAV; no identities or rankings in UI payload |
| Order / A/B | PASS | Six/six unique, seven/seven with repeats; complementary reviewer assignments; >=4-position repeat gaps |
| Reproducibility | PASS | Repeated preparation produced identical clip and HTML hashes |
| Contracts | PASS | 10 Python tests plus JS contract and UI transport suites |
| Save / resume / export / reviewer separation | PASS at contract and DOM-adapter level | Partial in-memory technical fixture roundtrip; JSON/CSV; wrong-reviewer and unknown-field rejection; stale-tab guard; withdrawal |
| Real Chromium / native browser storage / audible output | BLOCKED / NOT RUN | Chromium startup denied by sandbox, `sandbox_host_linux.cc:41`, `shutdown: Operation not permitted (1)` |
| Human acoustic agreement | NOT RUN | 0 human answers; `validation/no-responses.json` |
| Population accuracy / Recall@K / learning | NOT RUN | Outside scope |

The browser check is provided for reproduction outside this sandbox. No browser
success, screenshot, physical-device sound quality, or browser memory bound is
claimed. Python/libsndfile accepts every float-WAV stimulus. A local user still
needs to confirm actual browser playback and persistence before listening.

## What the tests establish

Hashes bind the source audio, license evidence, fixed windows and frozen model
results before decoding. Every presented X/A/B alias maps back to the expected
clip hash. Both pages contain all ten clips, no source paths, identifying metadata,
algorithm scores or answer key. CSP denies external connections and allows only
the exact embedded script and blob audio. Numeric/response fields are strictly
allowlisted; unknown fields such as `correct_answer`, names or scores are rejected.

The UI transport suite uses an in-memory `technical-test-only` package without
music or a real session key. It exercises enum events, unfinished state,
restore/delete, independent reviewer storage, and conflict handling. These are
mechanical fixtures, not invented listening judgments. The analyzer rejects that
kind; no technical response file was added to a human session or report.

Selection, ranks and predictions are organizer data in `frozen.json`, never UI
data. The original PI-v1 and Acoustic v1 artifacts are hash-pinned; their code,
normalization, missing policy, weights and published results are unchanged.
Comparisons selected for close tempo or contrasting aspects are relative to the
small frozen pool, not independently confirmed perceptual examples. In particular,
the selected tempo contrasts include half/double-time hypotheses; no estimated
BPM has become a ground-truth label through this pilot.

## Preparation detail and resources

An initial PCM16 guard rejected a decoded value above full scale before creating
a package. The final format preserves native float32 samples instead of clipping
or changing gain; case selection, source windows and model results stayed identical.
All ten float32 rounding errors are exactly zero. Three decoded excerpts contain
samples beyond full scale (13, 2 and 9,035 samples respectively; peaks 1.031875,
1.005872 and 1.096025). Browser/device output may clip them. This limitation is
retained in the listening evidence rather than hidden by stimulus normalization.

Final sequential preparation/test batch:

- CPU: **6.531721 s**; wall: **7.413066 s**.
- Peak child RSS: **638.597656 MiB**; two configured compute threads.
- Preparation and package verification have CPU/virtual-memory limits; no GPU.
- New audio downloads: **0 bytes**; dependency downloads: **0 bytes**.
- Existing Python 3.12.13 environment, Node, numpy and soundfile reused.
- Two private HTML packages, approximately 68 MiB each; no audio was published.

These measured totals cover the final batch recorded in
`validation/technical-tests.json`, not earlier editing/probe overhead. The earlier
successful preparation peaked at 638.773438 MiB. Chromium failed before opening
a page; listener-side browser RAM and physical audio output remain unmeasured.

## Interpretation and next action

This is a deliverable for collecting independent evidence, not an improvement
claim. Start with one real person using listener 1, and optionally a different
person using listener 2, without discussing responses. Keep each person's latest
JSON export separately. Empty or missing responses remain NOT RUN; agreement
uses only answered unique A/B comparisons with a non-tied prediction. Ties,
neither, uncertain, missing data and repeats are reported separately.

The sample has only ten recordings from three author groups and deliberately
dependent comparisons. No resulting pilot fraction should be called population
accuracy or used to tune coefficients against these same cases. Further learning
requires a larger authorized corpus, independent overall-acoustic labels and a
new evaluation split defined before model fitting.
