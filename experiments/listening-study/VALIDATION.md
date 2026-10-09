# Validation — Listening Study v0.1

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
