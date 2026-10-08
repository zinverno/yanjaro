# Acceptance gates — 2026-10-08

| Stage | Status | Evidence |
|---|---|---|
| Actual Yambda schema / bounded range reads | PASS | `reports/real-data-probe.json`; 123.4 MB payload |
| Actual small feedback preparation | PASS local | `reports/real-feedback-prepare.json`; 45,565 historical pairs |
| Complete audio pairs in probe | INSUFFICIENT | 1,018 matched IDs, zero complete pairs |
| Full embedding scan | NOT RUN | Estimated ~67 min payload / ~100 min with headroom; exceeds 60-min gate |
| Real training / weights / holdout accuracy | NOT RUN | No real `model.json` or quality metrics exist |
| HfFileSystem runtime probe | BLOCKED | ConnectError, no full-download fallback |
| Local focused tests | PASS | 20 passed; synthetic fixtures only |
| Local TestClient HTTP tests | BLOCKED | AnyIO blocking-portal timeout; 3 tests need hosted rerun |
| Notebook structure / syntax | PASS | 12 cells; execution in Colab NOT RUN |
| New manual Actions workflow | PREPARED | Requires default-branch registration before dispatch |
| Render / remote API acceptance | NOT RUN | Deferred by owner; no service created |
| Yandex ID mapping / 27-feature adapter | UNRESOLVED | No compatible feature supplier or public ID join |
| Catalog coverage / mood prediction | NOT ESTABLISHED | No such claim follows from this experiment |

See [REPORT.md](REPORT.md) for measured resource limits, methods and blockers.
