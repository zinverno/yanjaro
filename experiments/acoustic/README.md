# Yanjaro Acoustic Lab v0.1 — **experimental, standalone**

**Purpose:** begin training a *real* small personal music ranker, prioritising **tempo / pulse regularity / onset density / within-song energy and rhythm curves** for the current listening session. No genre labels, Yandex audio downloads, account tokens, scraping or Yanjaro runtime changes.

The existing Yanjaro `yanjaro/recommend.py` is a finite rule-based mix based on likes, artists and listening events. This is a separate acoustic experiment: keep the published `v0.2.0rc4` unchanged. Do not integrate until the prototype is evaluated on real permitted audio and explicit feedback.

## Setup (Manjaro, separate virtualenv)

```sh
cd experiments/acoustic
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Python 3.11–3.14 anticipated; dependencies are `librosa` + `numpy` (which can install heavier scientific dependencies transitively). The first run may spend time compiling numerical routines. Use 10–20 **local audio files you are permitted to process**. We DO NOT ship or train on live Yandex Music streams.

## Guided workflow

```sh
# 1) Analyze FIRST 90 seconds of up to 12 local audio files (opt-in)
.venv/bin/python -m acoustic_lab --workspace .local index ~/Music/Acoustic-Test --limit 12 --seconds 90

# 2) Note track IDs, approximate BPM and titles
.venv/bin/python -m acoustic_lab --workspace .local list

# 3) Create a session with one or two indexed songs that match your mood RIGHT NOW
.venv/bin/python -m acoustic_lab --workspace .local new-session evening-01 <SEED_TRACK_ID>

# 4) Get initial suggestions from a handcrafted rhythm-first acoustic baseline
.venv/bin/python -m acoustic_lab --workspace .local recommend evening-01 --limit 10

# 5) Explicitly mark which *non-seed* candidates fit now (not a global like/dislike)
.venv/bin/python -m acoustic_lab --workspace .local rate evening-01 <CANDIDATE_ID> yes
.venv/bin/python -m acoustic_lab --workspace .local rate evening-01 <OTHER_CANDIDATE_ID> no

# 6) Repeat across at least 6 distinct listening sessions (ideally >=20).
# Only now is a personalized learning model fitted and saved to .local/model.json.
.venv/bin/python -m acoustic_lab --workspace .local train
.venv/bin/python -m acoustic_lab --workspace .local recommend evening-01
```

`--workspace .local` keeps path names, acoustic features, labels, and model in a local git-ignored folder. All saved files are JSON readable without pickle and written owner-only. No source audio is copied or persisted. Audio file paths do remain in the **local** library index so you can reopen files; never commit `.local` or attach it to public reports.

## What it is (and is not)

- **Acoustic analysis:** librosa estimates tempo, detected beats/regularity, onset intensity/density, spectral brightness/flatness, bass-frequency ratio, overall energy and 6 equal-duration curves for energy, rhythm and brightness. These buckets are *not* verified verse/chorus segmentation. We analyze only the first `--seconds` seconds (10–300), not the whole song; the result must not be described as full-song structure.
- **Untrained fallback:** weighted acoustic distance, prioritizing rhythm, tempo, energy and temporal changes. A "recommended" track is one with similar descriptors, not a mood diagnosis.
- **Actually trained model:** with >=6 sessions each having at least one explicitly positive and negative *non-seed* candidate, constrained pairwise logistic regression learns how strongly to weight acoustic distances. A model is only saved when fitting finishes. This is learned ranking, **not a from-scratch audio network, audio generator or a trained emotion classifier**.
- **Validation:** hold out the latest ~25% *sessions*, never randomly split individual ratings. Report *pairwise ranking accuracy* for prior vs trained weights. This is an exploratory metric on sparse personal labels, not evidence of superiority over Yandex's recommendations, causal improvement, or general population accuracy.
- **Weak laptop:** CPU-only, at most 20 new files by default, bounded audio duration and sequential indexing. No GPU, cloud, embedding API or subscription. Indexing large music folders could take minutes or longer. Cache skips unchanged files.
- **Privacy/rights:** files stay local. No audio decoded from Yandex Music, no download from the service, no Yandex tokens or identifiers in training. If you use a third-party dataset, inspect the dataset's license and individual tracks. MTG-Jamendo materials are explicitly restricted to non-commercial research without separate authorization; don't ship that dataset or its trained artifacts with a commercial product without rights clearance.

## Definitions and constraints

Tempo/BPM is an imperfect estimate (can be half-/double-time). No reliable meter/time signature such as 3/4 vs 4/4 is inferred in v0.1. Waveform amplitude is not the same as perceived emotional energy; loudness/mastering can bias the global energy signal. Early implicit skips are not reliable negatives, so only explicit session judgments train the model. Different songs and short clips have different certainty; later versions need uncertainty/validity flags and proper section detection.

## Before connecting to Yanjaro UI

See `AGENT_TASK.md`. A feature lookup can only score catalogue tracks when their acoustic descriptors have been obtained from **authorized** sources. Track titles, artists and album art from the Yandex API do not reveal a track's actual BPM or waveform. Do not silently fetch its signed full-audio URLs to generate training data. The standalone experiment must remain opt-in, offline and removable.
