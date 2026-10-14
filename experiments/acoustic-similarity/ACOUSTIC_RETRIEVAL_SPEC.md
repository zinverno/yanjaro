# Frozen acoustic retrieval v1 and missing-data policy

Base HEAD: `277f26d56cc71bcca02a61d88414062f13f3ac6c`. This specification,
implementation, tests and study runner are committed before new real rankings.
No fitting, penalty sweep, human-label invention, or disclosed GMD test use.

- Feature schema: `pi610-lab-timbre85-energy10.acoustic-v1`, 705 coordinates.
- Distance schema: `hellinger-rms-equal-aspects.acoustic-v1`.
- Missing policy: `common-mask-coverage-first.v1`.
- Profiles: `pi_coverage_v2` isolates the missing-policy change on PI-v1 features;
  `acoustic` adds existing DSP timbre and energy. Historical PI-v1 remains intact.

## Missingness, distances and ordering

Nine atomic blocks, in fixed mask order: P0/P1/P2/P3 (four periodicity bands), I
(normalized intervals), R (density), H (tempo hypotheses), T (timbre), E (energy).
Unknown histograms become **null**, never a zero-vector match, 0.5 penalty or
maximum acoustic difference. Each null has a reason. A missing band does not
discard other available bands. PI ABSTAIN still permits T/E comparison.

For each pair take the intersection of available blocks. Store atomic distances,
missing identities/reasons, common mask and coverage separately. If nothing is
shared, ABSTAIN. Unknown for one and for both records follows the same rule.
Coverage measures **availability**, not correctness or confidence: estimated
tempo remains unverified even when its histogram is present.

Fixed integer weights avoid floating-point ambiguity in coverage tiers:

| Profile | P0 | P1 | P2 | P3 | I | R | H | T | E | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pi_coverage_v2 | 1 | 1 | 1 | 1 | 4 | 4 | 4 | — | — | 16 |
| acoustic | 1 | 1 | 1 | 1 | 4 | 4 | 12 | 12 | 12 | 48 |

Acoustic therefore gives rhythm (P/I/R together), tempo, timbre and energy **1/4
each** with complete data. The PI-only profile retains the old P/I/R/H weights.

For total weight W and common set C:

```
coverage = sum(u[k] for k in C) / W
weighted_numerator = sum(u[k] * d[k] for k in C) / W
D_common = weighted_numerator / coverage
conditional_score = 100 * (1 - D_common)
```

No distance is imputed for a missing block. Neither weighted_numerator nor
conditional_score is compared across masks. The deterministic overall order is:

1. More common weight first.
2. For equal weight but different masks, fixed lexicographic mask order with
   available before missing in P0/P1/P2/P3/I/R/H/T/E order.
3. Only within an identical mask: lower D_common first, then ID for exact ties.

This is an explicit **coverage-first retrieval policy**, not a perceptual theorem.
A complete but acoustically distant candidate can precede an incomplete close
candidate. More availability does not certify a correct tempo. A one-bit dropout
can change many ranks abruptly; these transitions must be reported. The arbitrary
fixed equal-weight mask order is administrative, not a hidden acoustic score.

For an unknown-tempo query all candidates lack shared H. They can still be
compared on their common P/I/R/T/E with 75% coverage. Known-tempo queries place
unknown-tempo candidates in a separate lower coverage tier. Removing the u01 hub
through this rule is an expected policy effect, never evidence of improved quality.

Each aspect can change the **unrenormalized numerator** by at most 0.25; with full
coverage this also bounds its change to D_common by 0.25. At 75% coverage, a whole
remaining aspect can change D_common by at most 1/3; only one surviving aspect can
control all of it. Scores on these different coverage levels are not interchangeable.

## Fixed normalization and mathematical distances

Reuse unchanged PI-v1 features: per-band positive-lag autocorrelation histograms,
median-normalized interval histogram, two density coordinates and the tempo
hypothesis histogram. Histograms have unit mass; density is already in [0,1].
P bands, I and H use `sqrt(sum((sqrt(p)-sqrt(q))**2)/2)` (Hellinger distance).
R uses mean absolute difference. Rhythm distance is the weighted mean of the
available P/I/R atomic distances; H is explicitly excluded.

Reuse unchanged Lab DSP vectors: 85 timbre coordinates (MFCC mean/std/deltas,
brightness, flatness, low-band proportion, temporal brightness curve) and ten
energy/dynamics coordinates. Their historical physical scales and clipping to
[-3,3] remain unchanged. Divide each coordinate by 3, giving [-1,1], then use
`sqrt(mean(((x-y)/2)**2))` separately for T and E. Equivalently, take RMS of raw
coordinate differences divided by 6. RMS avoids dimension-count inflation and
the additional numerical compression of the historical squared-MSE distance.

All component distances are bounded in [0,1] and dimensionless. No corpus mean,
variance, rank statistics or observed spread is used to normalize them. Equal
ranges/budgets do not imply equal empirical influence or perceptual calibration;
that remains an evaluation question. Timbre/dynamics temporal curves can depend
on window position, so the **overall** representation is not phase-invariant.

No old DSP BPM, rhythm vector, overall score, learned Groove/cap2 weights or MERT
is included. H is added exactly once. Absolute-lag periodicity and event density
still contain speed information: arithmetic double-counting of H is removed,
but statistical correlation between rhythm and tempo is not claimed absent.

## Frozen experiment and diagnostics

Only the original ten local CC0 records and exact authorized 15-second windows.
Verify manifest, audio, rights evidence and both historical index hashes before
decoding. Missing originals or mismatches → BLOCKED, without acquisition.

Repeat PI and Lab DSP extraction twice on each window; require exact within-run
descriptor digests. Compare with the historical cached vectors with a predeclared
absolute tolerance 1e-6 for platform floating-point drift, recording exact equality
and maximum errors. Build the new index from the **unchanged validated cached
coordinates**; write both repeat receipts and current decoded-window hashes.
Rebuild the composition and require identical canonical index digests. Source
audio hashes are checked again after extraction. No raw audio/private paths output.

Synthetic fixtures: known pulse patterns and speeds; carrier 220 vs 2200 Hz at
identical attack times; gain 1 vs 0.2 at identical carrier/timing. Measure all
aspects, including cross-aspect sensitivity, without assigning musical relevance.
Tests also cover unknown query/candidate/both, partial/no-common features,
symmetry, aliases, deterministic ordering, JSON key order and aspect influence.

After freezing, execute original PI-v1, corrected PI-only and acoustic retrieval.
Store all nine other-source ranks per query and every baseline component. For
each of seeds 0..4, replace 1% histogram mass with a random unit-mass histogram;
perturb normalized T/E/R coordinates by uniform ±0.005 and clip to their ranges.
These are descriptor-space diagnostics, not waveform/mastering robustness tests.

Missing-data diagnostics: drop H from each one of the ten records separately,
then drop each of rhythm/H/T/E globally. Save full rank permutations, Top-3
overlap/order, Top-1 changes and coverage changes. Flag adjacent same-mask D gaps
≤0.005 as near ties (0.5 conditional-score points); this flag never changes ranking.
Cross-mask score gaps are undefined. No diagnostics are used to retune the policy.

CPU hard cap 540 s within the 600 s budget, two compute threads, virtual memory
hard cap 1 GiB (stronger than requested RSS cap). Numerical artifacts ≤2 MiB,
create-only. Existing locked dependency installation is separate infrastructure
traffic; research code is offline. No paid service, GPU, remote training or audio
publication. Human acoustic quality, independent accuracy and Recall@K: NOT RUN.
