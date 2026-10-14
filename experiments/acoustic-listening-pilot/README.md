# Local blind acoustic listening pilot v1

An isolated, offline pilot stacked on the frozen PR #10 head
`35aecde3311fa302e0ac1548d9c53f336ed9c928`. No old files, models, features,
scores, missing-data policy or rankings are changed. This directory is not part
of the player. Human acoustic quality remains **NOT RUN** until real listeners
voluntarily provide responses.

**If you will listen, do not open `frozen.json` or the organizer reports first.**
They reveal the selected recordings and algorithm predictions. Prior familiarity
with these recordings/rankings can already weaken blinding.

## Start listening

Open the privately prepared `listener-1.html` in a desktop browser. It contains
the permitted clips and works directly as a local file, with no server. Reviewer
2 must use `listener-2.html`; one person must not occupy both reviewer slots.
No names, accounts or network connection are needed. Do not upload the HTML.

1. Connect headphones or your usual speakers, set a comfortable volume, then
   keep the device and volume fixed. Check that X, A and B each play for 15 s.
2. Press **Начать / продолжить**. For each of the 14 presentations, listen to X,
   A and B and choose A, B, примерно одинаково, ни один, or не уверен.
   The question concerns the combined rhythm, tempo, timbre and energy.
3. Influencing aspect and confidence are optional. Nothing is selected by
   default. You can skip, return, edit, pause, or remove all local responses.
4. Progress is saved in this browser's localStorage, isolated by reviewer and
   package hash. File-origin storage behavior differs by browser; export JSON
   as a backup before closing, moving the page, or clearing browser data.
   **Восстановить JSON** accepts only the same reviewer/package.
5. At completion, voluntarily export JSON (preferred) or CSV. Those files contain
   responses and anonymous session tokens, not audio or identifying metadata.
   Keep them locally for the organizer's analysis. Do not send the HTML or key.

There is no automatic completion judgment or feedback about which answer an
algorithm would prefer. Do not discuss responses with the other reviewer before
both finish. LocalStorage is not encrypted; other users of the same OS/browser
profile could access it. Withdrawal removes browser data for this page; separately
delete any downloaded backups and ask the organizer to remove any supplied copy.

## Reproduce preparation (organizer only)

Use the already-installed Python environment from Acoustic Similarity with the
unchanged `numpy` and `soundfile` dependencies. No installation or download is
performed by these commands. Set `$PILOT_PYTHON`, `$APPROVED_MANIFEST` and
`$PRIVATE_PILOT_RUN` locally; the run directory must be new and outside the checkout.

```sh
cd experiments/acoustic-listening-pilot
"$PILOT_PYTHON" pilot.py prepare --manifest "$APPROVED_MANIFEST" --out "$PRIVATE_PILOT_RUN"
"$PILOT_PYTHON" verify_local.py --run "$PRIVATE_PILOT_RUN" --out /tmp/pilot-package-check.json
xdg-open "$PRIVATE_PILOT_RUN/listener-1.html"
```

Preparation verifies the pinned manifest, audio and evidence hashes before any
decoding, verifies historical native-window hashes, and fails on missing or
changed inputs. No acquisition fallback exists. It creates two mode-0600 portable
pages, a private organizer key, and a numeric preparation receipt. Each page is
about 68 MiB because it embeds all ten losslessly represented decoded windows.
Only the small receipts may be copied to the public validation directory.

Exact native sample rates, channels, gain and windows are preserved. WAV contains
only `fmt`, `fact`, and `data` chunks, without titles or source metadata. Float32
preserves decoded MP3 overshoots; ordinary playback hardware may clip those peaks.
No loudness normalization, fades or time stretching is applied. Overall energy
judgments can therefore include mastering/gain differences.

The existing PR #9 portable demo was inspected: its exporter intentionally accepts
synthetic studies only; its collection service adds server/SQLite/recruitment
contracts unnecessary here. This pilot follows its offline, hash-bound presentation
pattern and reuses PR #10's rights/hash/atomic-JSON helpers, without changing either
earlier experiment. Local browser persistence is specific to this new pilot.

## Frozen design and later analysis

See [PROTOCOL.md](PROTOCOL.md) for selection and analysis rules. Twelve unique
triplets plus two reversed blind repeats; seed `2026101401`; all ten recordings
occur as anchors. Each reviewer gets six/six canonical A/B orientations for the
unique cases and seven/seven including repeats. Repeat separation is >=4 positions.
The second reviewer uses complementary A/B assignments and a different order.

`frozen.json` holds the exact selection, predictions' input distances/ranks,
coverage, artifact hashes, and organizer schedules. It is **not** sent to the page.
`freeze` is a create-only command for reproducing that file in an empty copy;
ordinary `prepare` verifies it and cannot replace it.

After voluntary real responses, use one latest export per independent reviewer
(JSON **or** CSV, never both copies of the same session):

```sh
"$PILOT_PYTHON" pilot.py analyze --key "$PRIVATE_PILOT_RUN/organizer-key.json" \
  --out /tmp/pilot-real-report.json /path/to/anonymous-response.json
```

With no response paths, the report is `NOT RUN`. Nonempty reports give per-reviewer
and descriptive total agreement numerators/eligible denominators, unanswered,
tie/neither/uncertain counts, optional aspects/confidence, complete/missing cases,
algorithm disagreements, cross-reviewer judgments and repeat consistency decoded
to recording identity. Repeats never count twice in primary agreement. Exact
algorithm ties are excluded from its binary agreement denominator. Coverage-first
decisions remain visible; conditional scores from different masks are not compared.

This does not establish population accuracy, Recall@K or model improvement. Ten
selected excerpts from three author groups cannot support general training. The
next evidence needed is independently collected acoustic judgments on a larger,
rights-cleared set of recordings and authors, with a held-out evaluation defined
before learning. No such acquisition, recruiting or training is started here.

## Tests

```sh
"$PILOT_PYTHON" -m unittest discover -s . -p 'test_*.py' -v
node test_contract.cjs
node test_ui.cjs
```

Contract/DOM-adapter tests use only in-memory `technical-test-only` fixtures with
no music or human identity. The analyzer rejects this kind. They do not create
human response artifacts or count as listening evidence.

Optional real-browser checks use an **already installed** Playwright Core and
Chromium, a fresh isolated profile, muted playback, and blank real sessions only:

```sh
PLAYWRIGHT_CORE=/path/to/playwright-core CHROMIUM=/path/to/chromium \
  node browser_check.cjs "$PRIVATE_PILOT_RUN" /tmp/pilot-browser-check.json
```

The test does not select acoustic answers. It checks float-WAV playback clocks,
duration, empty-session resume/import/export, reviewer isolation, mobile layout,
blind DOM, console and attempted web requests. In the agent sandbox Chromium
startup is **BLOCKED** by `Operation not permitted`; do not treat Node tests or
libsndfile decoding as an end-to-end browser PASS. Actual device output and browser
RSS during listening remain unverified. See [VALIDATION.md](VALIDATION.md).
