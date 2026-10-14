# Overall acoustic listening pilot v1 — frozen selection protocol

Base: PR #10 at `35aecde3311fa302e0ac1548d9c53f336ed9c928`. This pilot
does not extract features, recompute ranks, fit weights, or modify previous results.
Only the ten hash-bound CC0 originals and their previously approved 15 s windows
are eligible. Seed: **2026101401**. No human answers exist at freeze time.

## Case selection (12 unique anchor/unordered-candidate triples)

Use stored original PI-v1 ranks and stored Acoustic Retrieval v1 ranks/components.
Take two unused cases in each category, in this fixed order:

1. Small first/second acoustic margins, identical coverage masks, ascending gap.
2. Unknown tempo: u01 as anchor (first versus third acoustic neighbor), then
   u01 as candidate against the first acoustic neighbor of another anchor.
3. Partial features: s04 as anchor (first versus second acoustic neighbor), then
   s04 as candidate against another anchor's first acoustic neighbor.
4. Relatively close tempo with different timbre/energy: both pairs fully covered;
   sort by maximum tempo distance, then descending absolute difference in the
   mean timbre/energy distances. Candidates must differ on that mean.
5. Relatively close rhythm with different tempo: both pairs fully covered;
   one candidate is closer in rhythm and farther in tempo; sort by its rhythm
   distance, then descending tempo contrast.
6. PI/acoustic disagreement: each algorithm's first neighbor, when different;
   sort by descending sum of the opposing ranks.

For categories 2/3 the anchor case is mandatory first. For all other choices,
prefer an anchor not yet selected, then apply the numerical ordering above,
then lexical (anchor, sorted candidates). Skip duplicate triples. These are
relative contrasts in this tiny pool, **not calibrated semantic thresholds**.
Selection statistics and all eligible/selected values are reproducible from the
frozen artifacts. No aspect rescaling or distance tuning is performed.

## Presentation

Twelve base cases, with six canonical-first candidates in A and six in B.
Repeat one case of each orientation, reverse A/B in each repeat: total 14,
seven of each orientation. Deterministic SHA-256 seed ordering; a repeat is
at least four positions after its first occurrence. Reviewer 2 uses complementary
base orientations and an independently shuffled order. No timestamps, names,
demographics, source IDs, titles, authors, genres, scores or predictions in the
response schema or presentation. Reviewer tokens distinguish sessions, not people;
the organizer must ensure different people use separate packages.

Question: «Какой вариант акустически ближе к исходной композиции по совокупности
ритма, темпа, тембра и энергии?» Choices: A / B / примерно одинаково / ни один /
не уверен. Influencing aspect and confidence are optional, blank by default.
No answer is preselected, inferred from playback, or supplied by an algorithm.
Skipping, pausing, changing a response, and withdrawing locally are allowed.

Keep playback volume/device constant. Clips preserve native sample rate, channels
and gain, with no loudness normalization, time stretch, fades, or expanded windows.
They are metadata-free float32 WAVs; float rounding is documented and checked.
Float preserves decoded MP3 overshoots without clipping or gain changes; output
hardware/browser may still clip values above full scale. PCM16 preparation was
rejected before package creation because one decoded input exceeded full scale.
Thus level/mastering differences may influence judgments of energy. One player at
a time. Embedded clips and presentation keys never leave the local machine.

## Analysis fixed before listening

The organizer key stores predictions separately from responses. Compare original
PI-v1 and Acoustic v1 independently. Acoustic prediction follows its frozen
coverage-first ranking; score gaps across different masks are not comparable.
Exact same-mask distance ties (tolerance 1e-12) are reported as algorithm ties;
lexical tie-breaking is not acoustic evidence.

Report each anonymous reviewer separately, then descriptive totals. Main agreement
denominator: answered unique cases with A/B judgments and a non-tied prediction;
no repeated trials in that denominator. Separately count ties, neither, uncertainty,
unanswered cases, optional confidence/aspects, missing-data cases, algorithm
disagreements, reviewer disagreements, and the two within-reviewer repeats.
Repeat consistency compares decoded candidate identity, not the displayed letter.
No population accuracy, Recall@K, significance claim, or model improvement claim.
No responses means **NOT RUN**, never zero accuracy or a synthetic evaluation.

## Limits

Ten excerpts from ten recordings and only three author groups; comparisons share
tracks and are dependent. Cases are deliberately informative and not a random
music sample. They concern these 15 s excerpts, not whole-song quality. Two
reviewers cannot establish generalization or train a general acoustic model.
Do not inspect the organizer key or historical rankings before your own listening;
previous exposure is a limitation of blinding. Do not recruit automatically.

Runtime budget: <=600 CPU seconds, <=1 GiB RAM, two compute threads. Zero new
audio downloads, training, paid services, GPU, deployment or audio publication.
