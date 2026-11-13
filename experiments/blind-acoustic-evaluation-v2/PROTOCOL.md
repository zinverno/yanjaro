# Blind Acoustic Evaluation v2 — pre-response protocol

Status: protocol/tool preparation. Real indexing, trial freeze and human evaluation
are **NOT RUN**. The earlier nonblind «Логика»/Blurry observation motivates this
experiment; it is neither a label nor confirmatory evidence here.

## Scope and admission

One owner-selected pool of **12–16 new, distinct recordings**, chosen before
computing rankings or hearing any v2 answers. Record the four previously indexed
Yandex IDs and their recording groups in the private plan; exclude these, alternate
IDs of the same recordings, and the ten PR #11 pilot recordings. The owner reviews
recording identity, not just title equality. ID/group/hash checks cannot prove that
two different encodings are different recordings; the explicit novelty review is
required. Do not replace tracks after seeing rankings or answers.

Use only already available local files for which the owner has reviewed permission
for acquisition, analysis, local feature storage and the intended private listening
by both listeners. An account/subscription or a working API is not itself evidence
for those uses. Retain local evidence and its SHA-256 per track. This tool neither
fetches nor captures audio. No catalog scan, batch acquisition, audio upload,
training, model download, paid API, GPU or publication is part of this protocol.

The plan fixes each 15-second window before extraction (normally start=30 seconds
for a full track; start=0 for an already approved excerpt). No window optimization
after listening or ranking. Mono/stereo 8–96 kHz only; no loudness normalization,
clipping, resampling of the listening stimulus, or changed feature scales. Native
PCM is rendered to metadata-free float32 WAV, with rounding checked. Reject silent,
nonfinite, short or above-full-scale windows; choose suitable source material before
the run. A technical failure is preserved and not silently replaced or retried.

`prepare` requires an interactive local terminal and the exact consent phrase bound
to the plan SHA-256. Consent is recorded **before decoding or indexing**. No CLI
consent flag, environment switch, unattended pipeline or previous-run consent.
Output is create-only, owner-only, outside Git. All source, rights and audio hashes
are checked before and after extraction. At most 16 fixed windows, two compute
threads, 540 CPU seconds; a failed output directory is retained for diagnosis.

## Frozen comparators

The upstream commit and file hashes are in `upstream-lock.json`. No existing
experimental files, models, coefficients or PR #10/#11/#12/#13 are changed.

1. **Acoustic Retrieval v1**: existing `acoustic_retrieval.compare/search`, profile
   `acoustic`, schema `hellinger-rms-equal-aspects.acoustic-v1`.
2. **PI corrected**: the same existing functions, profile `pi_coverage_v2`, missing
   policy `common-mask-coverage-first.v1`. This is not historical PI's distance=0.5
   substitution. Coverage and availability mask precede distance, unchanged.
3. **Tempo only v2 baseline**: Hellinger distance between the *same frozen PI tempo
   hypothesis histograms* used by Acoustic v1. Obtain the existing `tempo` atomic
   distance; no other aspect or fitted coefficient enters. Missing either histogram
   means abstention, never zero distance or a synthetic BPM. This definition is
   fixed here before data; it is not a claim of ground-truth tempo.

ID is a deterministic ranking tie-break, not an acoustic prediction. For equal
coverage/masks and distance difference <=1e-12 predict `tie`; if either candidate
has no common features, predict `abstain`. Preserve full rankings, coverage,
distances and pair predictions in organizer-only files before any response.

## Selection and blinding

Fixed seed **2026111301**, SHA-256 sorting with lexical tie-breaks (no dependence on
Python PRNG versions or input order). Enumerate X and unordered distinct A/B pairs
from the pool, requiring at least one candidate in the union of the three Top-3s.
Select **six algorithm-disagreement cases**, with at least two strict predictions
choosing different candidates, then **four consensus controls**, where all three
strictly choose the same candidate. Prefer unused anchors, then unused recordings,
then the fixed hash order. Consensus is not a correct human answer or an attention
check. Never exclude a listener because they disagree with a control.

Add **two reversed repeats**, one selected deterministically from each group:
**12 presentations = 10 unique cases + 2 repeat controls**. The repeats are excluded
from agreement totals; report consistency separately. If either quota is impossible,
stop with BLOCKED before issuing listener pages. Do not change quotas/seed or shop
for a favorable pool; a revised design requires a new version before any answers.

Prepare exactly two anonymous independent listener slots. Ten originals have five
canonical A and five canonical B positions; select opposite-orientation repeats so
all twelve have six/six balance. Listener 2 gets complementary A/B orientation and
an independently shuffled order. Each repeat follows its original by at least four
positions. All schedules are frozen together. A single listener is allowed by
withdrawing the unused slot at closeout; between-listener evidence is then NOT RUN.
Order uses the first valid hash permutation with salts `[order, slot, attempt]`,
attempts 0–999, accepting only schedules satisfying the repeat gap. This is a fixed
schedule construction rule, with no inspection of responses or change of seed.

Reuse PR #11's offline UI/storage/import/export/withdrawal design. Listener pages
contain only opaque identifiers, X/A/B audio and the neutral question about overall
acoustic similarity. No title, artist, algorithm, score, prediction, group, source
path, recording ID or organizer key. Pages make no external requests. Identifying a
song by ear remains possible: blinding concerns the algorithms, not guaranteed song
anonymity. Keep the organizer folder inaccessible to listeners until closeout. An
owner who examines rankings must not claim to be a blind listener; use another
organizer or listen before opening organizer artifacts.

Answers: `A`, `B`, `tie`, `neither`, `uncertain`; skipping leaves `null`. Optional
dominant aspect: rhythm/tempo/timbre/energy/combination; optional confidence 1–5.
There is no preselected answer or feedback. Keep playback device/gain fixed, allow
breaks and replays. Responses are anonymous browser-local exports, stored separately
under `responses/`; never append them to predictions or use them during selection.
Withdrawal removes browser state; previously exported files require separate deletion.

## Closeout and descriptive analysis

Before listening, retain the sealed freeze digest separately; it binds the plan,
consent, source versions, index, predictions, schedules and page bytes. No response
files exist at freeze. Closeout explicitly marks each slot completed or withdrawn,
bound to that seal. Analyze only after both slots are closed, using exactly one
export for every completed slot and none for withdrawn slots. A completed session
may contain skipped questions; count them, never silently drop them. Conflicting or
duplicate exports, foreign packages/tokens, extra fields and technical fixtures fail.

For each ranker report **matches / eligible decisive responses** and its fraction:
eligible = original-case A/B answers with a strict model preference. Human ties,
neither, uncertain, skipped, model ties and model abstentions are separate counts,
never wrong answers or half-points. Also show exact human/model tie counts, without
mixing them into the decisive denominator. Report each listener separately, pooled
response counts (not independent sample size), disagreement/consensus selection
groups, complete/partial feature groups, and optional aspect groups. No answers
means NOT RUN; zero eligible means fraction=null.

Between listeners, map A/B to canonical recording identities before comparison.
Report A-vs-B discordance among jointly decisive original cases, plus the complete
category cross-tab (tie/neither/uncertain/skipped included). Do not call uncertainty
a disagreement. Report reversed-repeat consistency separately, with only two
repeat pairs per listener. Include counts of neither and tie, pool size, used
recordings, artist groups and all denominators. Do not remove inconvenient listeners,
cases or aspects after seeing responses.

These are selected, dependent comparisons from one small convenience pool and at
most two listeners. **No population accuracy, Recall@K, statistical superiority,
model improvement or perceptual calibration claim.** No hypothesis significance
test or tuning. This v2 set is evaluation-only for the frozen comparators. If its
answers later inform any design/weight/scale choice, it becomes development data:
confirmation then requires new unseen recordings and new responses under a new
preregistered protocol. Never tune and confirm on these same answers.
