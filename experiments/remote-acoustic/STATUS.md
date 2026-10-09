# Acceptance gates — 2026-10-09

| Stage | Status | Evidence |
|---|---|---|
| TestClient hang root cause | PASS | EPERM on asyncio wakeup socket; diagnosis receipt |
| Complete local experiment suite | PASS | 40 passed, zero skips; original HTTP assertions retained |
| Hosted experiment CI | PASS initial | 23/23 at 630bed0; final expanded run is linked on PR #7 |
| Starting Arch/Manjaro CI | PASS | Both succeeded at supplied 079a9b4; distribution checks only |
| Actual ID-only coverage analysis | PASS | 30.53 MB new traffic under 32 MiB cap; no new vectors |
| Explicit row-group extraction | PASS cached real data | Group 29 only, 119,573 rows / 1,018 matched IDs |
| Sufficient complete pairs within 512 MiB | FAIL | All 59 feasible group sets yield zero full pairs |
| Full-table structural coverage | PASS analysis | Up to 32,171 complete pairs; unread vectors not validated |
| Workflow source/input review | PASS | Manual-only, read-only, probe-only; injection/ref tests |
| Separate registration PR | PASS preparation | Draft PR #8, exactly one YAML file |
| Registration merge / hosted probe | NOT RUN | Awaiting owner's registration approval |
| Larger vector scan / real training | NOT RUN | No larger budget approved, no real weights or quality metrics |
| Notebook structure / syntax | PASS | 12 cells; Colab execution NOT RUN |
| Render / remote API acceptance | NOT RUN | Deferred; no service created |
| Published Yanjaro / Release / AUR | PASS isolation | No changes; PR #6/#7 unmerged |
| Yandex ID mapping / 27-feature adapter | NOT RUN | Incompatible spaces; mapping remains unresolved |

See [REPORT.md](REPORT.md) for exact evidence, conditional scaling design and the post-approval probe command. Synthetic fixture training is never real-model evidence.
