# Rhythm PI-v1: frozen untrained baseline

This specification and implementation are committed **before** computing real-song
pairwise distances. Source base: `c9ca0bfd87fd9bbc12f42aa27eacdd66963c3dfa`.
No train/validation/test fitting, GMD test inspection, genre, title, author,
preferences, corpus mean/variance or selected downbeat enters this formula.

Schema: `onset-pairac128x4-ioi32-density2-tempo64.pi-v1` (610 coordinates).
This is an independent experiment, not a replacement for the v1 or v2 schema.

## Signal and normalization

Use exactly the authorized 15-second native-rate mono mean. Reuse the unchanged
`rhythm_v2.spectral_attacks` detector: centered 32 ms Hann, 2 ms hop, positive flux,
four bands 0–200/200–800/800–3000/3000–8001 Hz, 5% peak prominence and 32 ms spacing,
with waveform energy-rise refinement. Discard candidates in the first/last 32 ms:
outside-window context is unavailable and must not be decoded. No drum recognition.

Let events be `(t_i, f_ib)` with nonnegative band flux strengths, `T=15 s`.
At least eight events with summed flux ≥20% of the window maximum are required.
Otherwise ABSTAIN; silence is also ABSTAIN. Compress positive strengths by square
root after scaling by their maximum. This retains relative accents and is invariant
to uniform gain (apart from the silence floor/detector numerical effects).

All histograms below use linearly interpolated bin assignment, Gaussian smoothing
σ=0.75 bin (`mode=nearest`), then unit mass normalization. Out-of-range interval
ratios saturate at the endpoints. There are no fitted statistics.

1. **Periodicity P: 4 × 128.** In each band retain events with raw band flux ≥20%
   of that band's maximum. For every pair `i<j` with `0.04≤τ=t_j−t_i≤4 s`, add
   `sqrt(f_ib f_jb)/(T−τ)` to a log2-lag histogram between log2(0.04) and log2(4).
   This is the positive-lag autocorrelation of a weighted impulse train, integrated
   over lag bins, with finite-window exposure correction; it is not circular bar AC.
   The per-window strength scale cancels in histogram normalization. No zero lag.
2. **Intervals I: 32.** On the summed-flux strong events take adjacent gaps `g_i`.
   Histogram `log2(g_i/median(g))` over `[-3,3]`, weighted by the geometric mean of
   the two square-root-compressed event strengths. Unknown BPM does not block it.
3. **Density R: 2.** Raw candidate rate `r=N/T` and effective rate
   `e=(Σw_i)²/(T Σw_i²)`, with `w_i=sqrt(Σ_b f_ib/max_i Σ_b f_ib)`.
   Map each with `x/(x+4)`. Density is a feature, never confidence.
4. **Tempo H: 64.** Reuse `rhythm_auto.tempo_candidates` on strong events at canonical
   origin `t_i−t_first+0.032`: 5 ms raster, 10 ms smoothing, mean-subtracted linear
   FFT AC, lag-zero and finite-overlap normalization. Keep at most four positive
   local AC peaks with score ≥0.1, estimated BPM in [40,260]. For each peak assign
   mass `ACscore × {0.25,0.5,0.25}` to half/main/double tempo within [40,260].
   Accumulate a log2-BPM histogram and normalize. Candidate masses are **not**
   calibrated probabilities of the musical tempo. With no qualifying peak, the
   whole tempo block is zero and `tempo_status=UNKNOWN`.

Primary primitives: [SciPy correlation](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.signal.correlate.html)
and [peak selection](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.signal.find_peaks.html).
Their mathematical behavior does not validate musical interpretation.

## Frozen symmetric distance

For two unit-mass histograms, `h(p,q)=sqrt(Σ_k(sqrt(p_k)−sqrt(q_k))²/2)`.
If either histogram has zero mass, use **0.5**, also when both are unknown.

```
d_P = mean over 4 bands of h(P_a,b, P_c,b)
d_I = h(I_a, I_c)
d_R = mean(abs(R_a - R_c))
d_H = h(H_a, H_c)
D   = (d_P + d_I + d_R + d_H) / 4
score = 100 * (1 - D)
```

Each saved contribution is `d_component/4`; the four contributions sum to D.
All are bounded and symmetric. Missing evidence uses a neutral dissimilarity,
so this is **not a mathematical metric**: unknown-vs-itself can have D>0.
Score is numerical proximity, not accuracy, probability, a musical grade, or proof
that the first neighbor is correct. Every indexed real record is UNVERIFIED.
Multiple tempo peaks, sparse bands and detector density >12 events/s are reported;
none of these flags changes weights or chooses a more convenient hypothesis.

Search ranks ascending D, then ID for exact ties, excluding the query ID, identical
audio hashes and the same recording group. All others must use this exact schema.
The saved DSP baseline is compared by its **rhythm component** and neighbor rank
overlap, never by the numerical distance scale or its timbre/energy overall score.

## Invariance and information loss

Downbeat is explicitly UNKNOWN and unused; no beat-phase uncertainty is invented.
Translating a fixed set of interior events leaves pair lags, intervals and density
unchanged; canonical tempo origin removes raster origin dependence. Waveform
translation is only approximately invariant because of the STFT/refinement grid.
Moving a real excerpt boundary can add/remove musical content and is not guaranteed
invariant. Edge exclusion is part of that limitation.

Unlike strict Rhythm-v2, this representation cannot retain beat-one identity,
bar-relative accents, event ordering beyond pair statistics, or cross-band
coincidence. Different patterns can share autocorrelation and interval histograms.
Half/double tempo ambiguity is softened in H, not erased in P or density. The same
rhythm at a different speed therefore need not have zero distance. Reweighting
accents changes pair strengths; phase independence is not accent invariance.
Tonal transients, reverberation, stereo cancellation and missing weak events can
affect the descriptor. A broad histogram from a dense mixture can look close to
another broad histogram without reliable musical similarity.

## Execution boundaries

Only the ten hash-bound PR9 local CC0 recordings and their original windows.
Check all audio and evidence SHA-256 before decoding. Missing inputs → BLOCKED.
No networking in study, new packages, audio publication, fitting, GPU or production
integration. Two compute threads; process CPU hard cap 540 s (requested ≤600 s);
virtual memory hard cap 1 GiB (stronger than RSS limit). Numerical outputs ≤2 MiB,
create-only, including source hashes and the frozen policy written before decoding.
Synthetic tests precede real extraction. No retuning after viewing real results.

Independent song-level acoustic rhythm labels: absent. Real accuracy/recall and
claims of better neighbor quality remain NOT RUN. A later review protocol may
select informative cases, but must not assign answers from either formula.
