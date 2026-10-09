# Validation — recruitment preparation

All audio, sessions and screenshots in automated checks are **synthetic demo**, not listeners. Continued from the exact user-specified draft PR #9 HEAD `3eacfc819deeeb507c25c286bed3deacc7ea204e`; main was `1c83c3776de565ed57416015f32a7ddd999af29f`. Same experimental branch, no rewrite/merge of #6/#7.

| Gate | Status / evidence |
|---|---|
| Local Python checks | PASS; 50 tests covering old study invariants plus collection, concurrent allocation, retry, resume, erasure, retention, closed intake and shortlist unknowns |
| Collection browser acceptance | PASS at `072aa2a49ba1f1c08e65125fe34db8e3cd3dcc48`; [run 37894472954](https://github.com/zinverno/yanjaro/actions/runs/37894472954), 12 scenario groups, Chromium 153.0.8010.12 and WebKit 26.6 (iPhone 13 profile), zero external page requests / JS errors |
| Existing standalone demo browser acceptance | PASS in same run, 17 checks; memory-only export still works independently |
| Loss/recovery cases | PASS; real WAV, actual HTTP/SQLite, lost acknowledgement **after** commit, retry without duplicate, tab close + process restart, new-browser recovery/revoked old cookie, completion failure/retry, mobile withdrawal failure/retry |
| Real music shortlist | PASS as research inventory: 24 named records / 3 creators, declared CC0-1.0, exact source/evidence levels, private listening CSV; no audio/feature fabrication |
| Admission of 24 real clips | NOT RUN; no files acquired, rights receipts/individual track checks and human review still pending |
| Ready to recruit publicly today | **FAIL**; approved real stimuli, production HTTP/HTTPS acceptance, responsible operator/contact and 3–5-person pretest not completed |
| Actual Android/iPhone/Zen + headphones | NOT RUN; emulation cannot establish physical-device/audible acceptance |
| SurveyCircle listing/code redemption, public TLS/load/provider logging | NOT RUN; no listing/deployment/account/payment performed |
| Existing Yanjaro / Release / AUR / Render / Yambda training | NOT RUN; untouched/out of scope |

The evidence above identifies its tested code. Later changes add direct aggregate analysis (no stale raw exports), UTC expiry, purge without traffic, permanent intake closure, and clearer UI errors. The workflow tests each subsequent exact PR head; consult [PR #9 checks](https://github.com/zinverno/yanjaro/pull/9/checks) for final-head status, not this historical run alone.

New acceptance harness: `tests/collection-browser.cjs`; [machine-readable evidence](validation/collection-checks.json). The final launch gates, retention policy and neutral invitation are in [LAUNCH.md](LAUNCH.md). License evidence and unresolved checks are in [CANDIDATES.md](CANDIDATES.md). Direct FMA opens returned 403; primary FMA search-index records and artist pages are explicitly distinguished from archived rights clearance.

![Collection, desktop synthetic demo](validation/screenshots/collection-desktop.png)

[Mobile WebKit](validation/screenshots/collection-mobile.png) · [Completed collection](validation/screenshots/collection-finished.png). Browser screenshots from the cited run; only the random demo recovery code is masked by Playwright (magenta), no image editing.

Reproduce from this directory: `python -m unittest discover -s tests -v`, generate a fresh `demo`, then run both `tests/browser.cjs` and `tests/collection-browser.cjs` with Playwright 1.63.0 + Chromium/WebKit. Local socket/browser restrictions remain; real HTTP/browser evidence is from CI, not an unrun local browser. Artifacts allow only synthetic screenshots/check summaries/aggregate metrics; never upload SQLite, real clips, cookies, raw answers or SurveyCircle codes.

---

# Historical validation — original offline v0.1

All input audio and answers in these checks are **synthetic demo**. No human listening results or real MTG audio were obtained. User explicitly limited this iteration to demo and pilot preparation.

| Gate | Status / evidence |
|---|---|
| Live main / #6 / #7 source inspection | PASS; exact SHAs in SOURCES.md |
| Separate branch from main | PASS; `experiment/listening-study-v01` |
| Local Python behavior tests | PASS; 34 tests, no skips (selection, aliases, unknowns, rights, frozen review, counterbalance, anonymous input, metrics, degenerate CI, cross-trial duplicates, versioned taskset) |
| Synthetic extraction/demo/analysis | PASS; 24 generated 8 s WAVs, 6 A/B + 2 C/D tasks, 16 scripted participants per wording |
| No network during demo extraction | PASS; test rejects every socket construction while building complete demo |
| JS syntax / dependency consistency | PASS; `node --check`, `uv pip check` |
| Local HTTP and local Chromium launch | NOT RUN to acceptance; sandbox denies socket operations with EPERM before page execution |
| Hosted browser/HTTP synthetic workflow | PASS; [run 37892275362](https://github.com/zinverno/yanjaro/actions/runs/37892275362), 17 checks, Chromium 153.0.8010.12, 0 external page requests, 0 JS errors |
| Desktop/mobile UI visual review | PASS; actual CI screenshots below, no song metadata, visible DEMO label, no horizontal clipping at 390 px |
| Real permitted music / listener pilot / hypothesis | NOT RUN, by explicit scope |
| Zen/Linux, Firefox, audible-device listening | NOT RUN; Chromium evidence cannot replace these |
| Existing player desktop tests in isolated study venv | NOT RUN successfully; attempted root discovery failed importing intentionally absent Qt/Yandex dependencies |
| Player / release / AUR / Render / Yambda training changes | NOT RUN; outside scope |

Environment: Python 3.13.13, NumPy 2.5.3, soundfile 0.13.1, cffi 2.1.1, pycparser 3.0. Local PyPI DNS was unavailable: the separate venv was installed offline from existing cached wheels reconstructed from their cached unpacked distributions. `uv pip check` passes. This is local functional evidence, not a clean package build. Hosted workflow installs the pinned requirements independently.

One initial numeric test found a tiny asymmetric floating-point tempo distance when swapping arguments. The implementation now computes `log2(max/min)`; the exact-symmetry assertion passes. Initial synthetic preparation also exposed overly broad dynamics from digital silence; the extractor now uses documented −80 dBFS floor and excludes silent frames from spectral means. Neither correction used human responses.

The first hosted run [37892040095](https://github.com/zinverno/yanjaro/actions/runs/37892040095) was **FAIL** in the invalid-Host test: Fetch did not deliver the overridden Host header. All preceding actual UI interactions had passed. The same 403 assertion now uses Node's explicit HTTP header API; repeat run passed without weakening the application check. That passed run corresponds to branch HEAD `94cf42dada79d29903adb8873a849d025eae09d3`, GitHub test merge `2d15b57f1c623e685f1c2fd466ee27d7b063732e`. Subsequent workflow runs check the exact PR head directly. Consult the PR checks for the latest head; this report does not call historical evidence an exact-head result.

The hosted run independently installed pinned requirements on Python 3.13.16. [Machine-readable browser evidence](validation/browser-checks.json), [synthetic feature ranges/conditions](validation/demo-feature-summary.json), [scripted metrics](validation/demo-results.json), [versioned demo tasks](examples/demo-taskset.json). The metric values are deliberately generated preferences, not outcomes measured on humans.

## Actual synthetic UI screenshots

Captured by `tests/browser.cjs`, Playwright 1.63.0 / Chromium 153.0.8010.12, 1200×1000 desktop and 390×844 mobile (full page), no DOM masking, no image manipulation. All three images visually reviewed after download from run 37892275362.

![Blind comparison, synthetic demo](validation/screenshots/comparison.png)

[Consent screen](validation/screenshots/welcome.png) · [Mobile screen](validation/screenshots/mobile.png)

Reproduction, from `experiments/listening-study`:

```sh
python -m unittest discover -s tests -v
python -m listening_study demo work/fresh-demo
python -m listening_study analyze work/fresh-demo/study.json work/fresh-demo/responses work/fresh-results.json
node --check listening_study/web/app.js
PLAYWRIGHT_MODULE=/path/to/playwright node tests/browser.cjs work/fresh-demo work/browser
```

Use a new output path each time. Browser checks require a host that permits ordinary loopback sockets and Chromium. No sandbox security setting is changed by the test harness. Synthetic screenshots and aggregate results are the only CI artifacts; audio and response files are excluded.
