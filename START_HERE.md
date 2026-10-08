# Yanjaro Acoustic Lab v0.1 — how to hand to your local agent

This archive contains **only** `experiments/acoustic/`, an autonomous CPU-first proof of concept, plus this guide. It does not replace any published Yanjaro Music application files.

1. In `/home/zinvernix/projects/yanjaro-music`, start a NEW experimental branch from current main (not the already published `v0.2.0rc4` tag).
2. Unzip this archive **into the project root**. It creates `experiments/acoustic/` and does not overwrite `yanjaro/`.
3. Read `experiments/acoustic/AGENT_TASK.md` and `README.md`. Execute its tests with a dedicated `.venv`.
4. For the first real-data test select local audio you have the necessary rights to analyze. Keep it outside Git, index 10–20 short files, record explicit current-session votes, then collect at least 6 varied sessions before training. For meaningful comparison aim for 15–30 independent sessions.
5. The code is a baseline + actual small trainable pairwise ranking model. It is **not a neural audio generation model**, an automatic long-term Yandex playlist listener, or a replacement for Yanjaro's current music recommendation feature.
6. No network/audio downloading and no account authentication are part of this POC. Later integration requires a legitimate source of acoustic features for catalog songs and a time-correct context snapshot.

Suggested agent instruction:

> Develop Yanjaro Acoustic Lab v0.1 as a separate experimental draft PR. Extract the archive into a new branch from main; run all tests and a bounded local-audio smoke test only after I select appropriate files. Do not modify existing Yanjaro playback, packaging, network access, the published release, or AUR. Review edge cases, data leakage, half-tempo BPM estimates, rights/privacy, and training/evaluation metrics. Show real PASS/FAIL/NOT RUN results, with no claim of increased recommendation quality until an actual comparison exists.
