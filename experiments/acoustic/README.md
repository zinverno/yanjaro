# Yanjaro Acoustic Lab v0.1 — **experimental, standalone**

**Purpose:** begin training a *real* small personal music ranker, prioritising **tempo / pulse regularity / onset density / within-song energy and rhythm curves** for the current listening session. No genre labels, Yandex audio downloads, account tokens, scraping or Yanjaro runtime changes.

The existing Yanjaro `yanjaro/recommend.py` is a finite rule-based mix based on likes, artists and listening events. This is a separate acoustic experiment: keep the published `v0.2.0rc4` unchanged. Do not integrate until the prototype is evaluated on real permitted audio and explicit feedback.

## Setup (Manjaro, separate virtualenv)

```sh
cd experiments/acoustic
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/synthetic_smoke.py
.venv/bin/yanjaro-acoustic --help
```

Validated on Python 3.14.7/Linux; other supported Python versions remain untested. Dependencies are `librosa`, `numpy` and `soundfile` (with scientific dependencies installed transitively). The first run may spend time compiling numerical routines. If using `uv`, `uv pip install --python .venv/bin/python -e .` is equivalent for the dedicated environment. See [VALIDATION.md](VALIDATION.md) for measured results and [validation/environment.txt](validation/environment.txt) for the tested dependency versions. The synthetic smoke generates its own WAVs and deletes them afterward. Use 10–20 **local audio files you are permitted to process** only after their owner selects them and authorizes indexing. We DO NOT ship or train on live Yandex Music streams.

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

Local data schema is now **2**: seed features are frozen when the session begins, and candidate features on their first explicit vote. Reindexing does not rewrite historical contexts or labels. Old schema-1 workspaces are rejected: keep them separately and create a new workspace. Repeat votes are idempotent; changed votes replace the label. Finish ratings before starting the next session. Training refuses feedback edited across the holdout time boundary. Run one CLI writer at a time; atomic replacement does not provide multi-process transactions.

Indexing decodes only local bytes through `soundfile`/libsndfile, without an external decoder fallback. WAV is tested; other formats depend on the installed libsndfile codecs. Unsupported formats (including typical AAC/M4A) produce explicit per-file errors. `--limit` bounds new/changed decode attempts, **including failed attempts**; unchanged/oversize files are skipped. Directory enumeration is not bounded by this limit, so use a small selected folder. Any per-file error gives exit code 2 with successful progress preserved; storage errors abort. Empty libraries can be listed, but cannot train or create sessions.

## What it is (and is not)

- **Acoustic analysis:** librosa estimates tempo, detected beats/regularity, onset intensity/density, spectral brightness/flatness, bass-frequency ratio, overall energy and 6 equal-duration curves for energy, rhythm and brightness. These buckets are *not* verified verse/chorus segmentation. We analyze only the first `--seconds` seconds (10–300), not the whole song; the result must not be described as full-song structure.
- **Untrained fallback:** weighted acoustic distance, prioritizing rhythm, tempo, energy and temporal changes. A "recommended" track is one with similar descriptors, not a mood diagnosis.
- **Actually trained model:** with >=6 sessions each having at least one explicitly positive and negative *non-seed* candidate, constrained pairwise logistic regression learns how strongly to weight acoustic distances. A model is only saved when fitting finishes. This is learned ranking, **not a from-scratch audio network, audio generator or a trained emotion classifier**.
- **Validation:** sort by timezone-aware session creation time and hold out the latest ~25% *sessions*, never randomly split individual ratings. Fit normalization only on training-session seed/candidate snapshots; both prior and learned weights use those scales for evaluation. Persist the split IDs. Report *pairwise ranking accuracy* (ties count as 0.5). The saved model is fitted on the training partition only. This is an exploratory metric on sparse personal labels, not evidence of superiority over Yandex's recommendations, causal improvement, or general population accuracy.
- **Weak laptop:** CPU-only, at most 20 decode attempts by default, bounded audio duration and sequential indexing. No GPU, cloud, embedding API or subscription. Indexing large music folders could take minutes or longer. Cache skips unchanged files.
- **Privacy/rights:** files stay local. No audio decoded from Yandex Music, no download from the service, no Yandex tokens or identifiers in training. If you use a third-party dataset, inspect the dataset's license and individual tracks. MTG-Jamendo materials are explicitly restricted to non-commercial research without separate authorization; don't ship that dataset or its trained artifacts with a commercial product without rights clearance.

## Definitions and constraints

Tempo/BPM is an imperfect estimate (can be half-/double-time). No reliable meter/time signature such as 3/4 vs 4/4 is inferred in v0.1. Waveform amplitude is not the same as perceived emotional energy; loudness/mastering can bias the global energy signal. Early implicit skips are not reliable negatives, so only explicit session judgments train the model. Different songs and short clips have different certainty; later versions need uncertainty/validity flags and proper section detection.

## Before connecting to Yanjaro UI

See `AGENT_TASK.md`. A feature lookup can only score catalogue tracks when their acoustic descriptors have been obtained from **authorized** sources. Track titles, artists and album art from the Yandex API do not reveal a track's actual BPM or waveform. Do not silently fetch its signed full-audio URLs to generate training data. The standalone experiment must remain opt-in, offline and removable.
