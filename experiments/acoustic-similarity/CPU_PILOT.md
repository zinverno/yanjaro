# CPU rhythm pilot v0.1

**Completed: real training PASS; quality improvement FAIL.** See
[CPU_REPORT.md](CPU_REPORT.md). The procedure below was committed before audio metrics
on `f1fe78b` (workflow syntax corrected on `c9e3742`); no model settings were tuned afterward.
This is a separate experiment, not a relaxation of `model.train`'s human/MERT gate.
The earlier 2,000-song collection plan remains a possible song study, not a prerequisite
for training a small rhythm metric. No pretrained encoder or GPU is used here.

## Actual sources and acquisition

[Official Groove MIDI Dataset](https://magenta.tensorflow.org/datasets/groove), Google
LLC, CC BY 4.0: 1,150 human-performed MIDI recordings, 13.6 hours, 10 drummers;
aligned audio is the synthesized output of a Roland TD-11. These are real performed
recordings, not generated random beats. MIDI events are independently recorded
annotations, not human judgements of similarity between songs.

Verified 2026-10-11: the complete audio ZIP is **5,111,599,714 bytes**; MIDI-only ZIP
**3,260,318 bytes**. The latter's published SHA-256 was verified locally. GCS answered
an actual range request with HTTP 206 and exact Content-Range. A pinned ZIP directory
lets us receive selected complete WAV entries; ZIP CRC32 is checked and each decoded
source receives SHA-256. The full audio archive SHA-256 is **not** claimed verified.
The immutable GCS generation, ETag, directory hash, official MIDI archive hash and
unmodified CSV row bind each selection. No extraction of archive-controlled paths.

[groove-cohort.json](datasets/groove-cohort.json) freezes 66 originals, **376,533,760
compressed audio bytes**. Admission uses a pinned digest of this entire plan.
Selection uses metadata/duration/compressed size, never acoustic scores or outcomes.
4/4 beats only; three originals per drummer/BPM group. Training budget 150 MiB,
validation 80 MiB, test 240 MiB; whole groups that fit, ordered by compressed size
then ID. The unused remainder of these per-split limits is not downloaded.

The downloader includes the **4,417,503 bytes** already received for local preflight
(MIDI archive, ZIP tail/directory, one 805,210-byte audio-entry probe) in the 512 MiB
limit. Remote audio + MIDI + directory + member headers fit with >140 MiB remaining.
It has no retries, no full-archive fallback, and reserves 2 MiB for protocol/artifact
metadata. Invalid status, range, ETag, hash, CRC or metadata aborts before training.
Resources and partial acquisition receipts survive ordinary errors. A forced process
kill can prevent the final resource receipt; Actions logs remain the evidence then.
No audio is uploaded in run artifacts; only features, annotation-derived targets,
source receipts, model JSON and measurements are preserved.

Attribution in the cohort and artifacts: Google LLC; Jon Gillick, Adam Roberts,
Jesse Engel, Douglas Eck, David Bamman, *Learning to Groove with Inverse Sequence
Transformations* (2019). [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Changes: selection, mono resampling, segmentation, features and annotation-derived
comparisons. No endorsement implied.

## Frozen task, splits and tempo control

Train: drummer1, drummer3, drummer5, drummer9, drummer10, 36 originals.
Validation: drummer7, 21 originals. Test: drummer8, 9 originals.
This deliberately replaces the canonical GMD split with a performer-disjoint pilot;
it is not comparable to published canonical-split results. Every derivative of an
original stays in its split. Audio/MIDI hashes and performer IDs cannot cross splits.
A single kit means **instrument-disjoint rhythm evaluation is not available**.

Four nonoverlapping bars per source, starting at beats 4/8/12/16. Exclude a bar only
if fewer than four MIDI grid cells contain hits; four such exclusions were found
in the annotation preflight. Targets use the official nine drum families on a
16-cell bar grid. Hit presence ignores velocity. Pair distance is binary Jaccard
on these MIDI annotations, independent of the audio feature extractor.

For each anchor choose up to four comparisons with MIDI distance gap >=0.15,
ordered by greatest gap and then source IDs. All three members must have **identical
annotated BPM** and three different originals from the same drummer/split. A positive
is *relatively closer in annotated drum structure*, not an independently reviewed
perceptual match. No genre label determines a target. This samples easier unambiguous
structural contrasts; it does not estimate performance over arbitrary song pairs.

Annotation-only preflight: train 140 bars / 332 triplets; validation 84 / 247;
test 36 / 88. Counts of used bars/originals are also reported, rather than treating
each correlated triplet as an independent recording. The small-data gate requires
>=3 training drummers, >=9 used training originals and >=60 train comparisons;
validation/test each >=3 used originals and >=20 comparisons. Rights/source checks
are separate from these feasibility minima. They are not a statistical power claim.

## Baseline and model

Audio feature schema `audio-flux-4bands-16phase-ac64-beat-normalized.v1`: four
spectral-flux bands pooled over 16 bar phases (64 values), plus 64 onset
autocorrelations at lags in beat units. Fixed per-band normalization; no fitted
statistics from held-out data. Annotated tempo maps seconds to beats. Neither MIDI
hits nor tempo magnitude, performer, source ID, genre, likes or dislikes enter the
learnable vector. Tempo-only distances tie every triplet: accuracy **0.5 by design**.
Tempo-normalization unit probes are explicitly artificial software tests.

Baseline: uniform diagonal distance over these same 128 features. Learned: 128
positive softmax diagonal weights, existing deterministic full-batch Adam,
300 epochs, lr=.1, L2=.01, margin=.05, temperature=.1. Only train triplets enter
optimization. Validation is reported without selecting hyperparameters; test is
computed once for this fixed candidate. The previous full-song DSP baseline has a
different schema/unit of analysis and is not presented as this pilot's comparator.

Artifact schema `yanjaro.rhythm-midi-head.v0.1` includes weights, schemas, cohort,
features/targets hash, code version, counts, settings and held-out metrics. Unit
fixtures never become published weights. Energy remains measured RMS/peak dBFS;
energy quality and training are NOT RUN without an independent target. Timbre is a
separate [NSynth note experiment](NSYNTH_PILOT.md), not part of this rhythm head.

Report triplet accuracy (ties .5), paired differences and per drummer/BPM groups.
Also report same-genre/different-rhythm and different-genre/closer-rhythm slices;
these use genre only after labels are fixed. Instrumentation slice is NOT RUN for
one kit. With one held-out performer in each split, population-level improvement
and artist-bootstrap confidence are **NOT ESTABLISHED**, even if sample accuracy
increases. Failure to beat the baseline must be reported.

## One remote run, isolated CI

[Workflow](../../.github/workflows/acoustic-similarity.yml): standard `ubuntu-24.04`,
CPU only, pinned Actions, Python and dependency wheels. PR attempt 1 runs tests
without data/model downloads. One explicit **Re-run all jobs** of that exact CI run
(attempt 2, initiated by zinverno on PR #10) admits the pilot; attempt >=3 does not.
There is no automatic training on pushes. Run budget: 20-minute job, 15-minute
process wall deadline, 600 CPU seconds, 4 GiB virtual memory, two numerical threads,
512 MiB data acquisition. No cloud provisioning or production secrets.

This uses GitHub's [manual rerun mechanism](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs),
which retains the original event commit. `workflow_dispatch` would require
[registration on main](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow);
main remains unchanged. Do not manually rerun other PR runs for training without
new authorization; the once-only limit is operational across run IDs. After the
one run, the report commit disables the pilot job until another approval.

```sh
# Authorized remote job only; no data retrieval during ordinary tests:
python -m acoustic_similarity.rhythm run \
  --plan datasets/groove-cohort.json --output runs/groove-cpu-v1

# Local inspection of an already obtained, hash-verified cohort original:
yanjaro-rhythm search /path/to/gmd-original.wav --bpm 120 \
  --model /path/to/artifact/model.json --catalog /path/to/artifact/dataset.json
```

Search reports ranked original IDs, averages distances over their bars, and excludes
all derivatives of the query original. It requires the known source's annotated BPM
and beat origin; arbitrary songs are outside this pilot's admission. The existing
`yanjaro-similarity` CLI remains the baseline for other cleared audio. A song-level
learned model needs tests with estimated beat phase, new kits, mixed instruments,
long-range structure and independently judged songs; these weights do not establish
those capabilities. Yandex ID/catalog limitations remain in [REMOTE.md](REMOTE.md).
