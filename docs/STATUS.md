# Status

Last updated 2026-11-16. This page says what exists, what is limited and what
is next. Numbers here come from running the commands shown.

## Scope

CivOps is a decision-support prototype for routing non-emergency calls to a
community-responder service, written at HackUMass XIV and finished afterwards.
The original plan had three tiers:

| Tier | Item | State |
|-|-|-|
| Must | Rulebook in version-controlled YAML, with unit tests | Done. Validated at load; see [Rulebook](RULEBOOK.md) |
| Must | Exhaustive completeness check | Done: 163,296 inputs |
| Must | Console runs a scripted call, extracts facts, cites a rule, shows the tripwire | Done |
| Must | Replay audit into four review groups | Done |
| Must | What-if staffing simulator | Done. Arrival timing is fitted, not calibrated to LEAP's tables; see Limitations |
| Should | Live call into the console | Partly: laptop microphone through Deepgram. No telephony |
| Should | Matched-pair bias audit | v1 run (uninformative for routing); v2 designed and pre-registered, not yet run |
| Should | Missed-escalation evaluation with a confidence interval | v1 run (no controls); v2 with controls pre-registered, not yet run |
| Stretch | Conformal abstention; caller-facing voice intake | Not started |

## What is implemented

**Decision layer**
- A YAML rulebook (`backend/rules/dispatch.yaml`, v0.2), parsed into immutable
  Pydantic models once and cached. Unknown keys, duplicate IDs, bad
  destinations and impossible schedules fail at load.
- A rule engine with a fixed stage order: tripwire, reported concern,
  incomplete screening, missing context, eligibility. Every decision carries a
  rule ID, a source and the rulebook version.
- A keyword tripwire on the raw transcript, in six categories.
- One-way autonomy: a recommendation that leaves the human dispatcher is
  provisional while any "no" it rests on is model-only.

**Extraction**
- One Claude call per transcript, returning structured output with an evidence
  quote per screening answer. The model is set by `CIVOPS_EXTRACTION_MODEL`.
- Deterministic post-checks: quote must be in the transcript; hedged denials
  are reset to unknown; malformed output counts as unknown.

**Console** (React, three screens)
- Live Call: transcript stream, tripwire banner, AI-proposed answers that need
  confirming, recommendation with rule and source, confirm or override (with a
  chosen destination and a reason), saved review log with CSV export.
- Monthly Audit: seeded synthetic month or your own file, four group filters,
  paging, row detail, CSV export, two charts.
- What-If Simulator: today's schedule from the rulebook, presets, schedules
  that run past midnight, two charts and a table with p10 to p90.

**Persistence**
- SQLite call log (calls, transcript segments, decisions, reviews). Transcript
  text is stored only for scripted calls unless a flag is set.

**Hardening** (localhost threat model)
- Origin and Host checks on every request and WebSocket handshake.
- Call IDs on every event; token-gated event injection, off by default.
- Size limits on every request field and list.
- No transcript text in logs.

**Tooling**
- CI: lint, tests with a coverage floor, evaluation case-file checks,
  dependency audits. Dependabot. A Makefile.

## Verification snapshot

| Check | Result (2026-11-16) |
|-|-|
| `python -m pytest -q --cov=app` | 482 passed; 98% line coverage of `backend/app/`; warnings are errors |
| `ruff check app scripts eval tests` | clean |
| `pip-audit -r requirements.txt` | no known vulnerabilities |
| `npm ci && npm run lint && npm test && npm run build` | clean; 77 tests |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities. (7 moderate advisories exist in dev-only lint tooling.) |
| Three scripted calls, in a real browser, through the real backend | Routine call: CRESS-001, provisional, then confirmable after confirming the answers. Hidden knife: TRANSCRIPT-TRIPWIRE. Reviews saved to the call log. Extraction was answered from a fixture: no API key was available. |
| Replay of 5,000 audit records | 0.07 s (was 10.3 s when the rulebook was re-parsed per record; same machine) |

## Known limitations

These are known and deliberate, or known and not yet done.

1. **Real Claude extraction of the three scripted calls has not been recorded.**
   The offline fixture is a hand-written ideal extraction and is labelled so.
   `python -m eval.record_demo_fixtures --yes` (3 paid calls) replaces it.
2. **The v2 evaluations have not been run.** Only v1 results exist, with the
   limits described in [Evaluation](EVALUATION.md).
3. **Arrival timing is fitted, not taken from LEAP's tables.** A test that the
   simulator reproduces the coverage figures is a regression check on the fit,
   not a validation. See [Data](DATA.md).
4. **The live microphone path was not exercised with real audio in the last
   round of changes.** Its logic (start, stop, drain, Deepgram errors) is
   covered by tests with a fake audio stack. It needs a manual run before a
   live demo.
5. **Extraction runs once, when the call ends** (and on demand). Only the
   tripwire screens the transcript while the call is in progress.
6. **The tripwire is lexical.** It does not understand negation and misses
   emergencies described without a listed word. Its accepted false positives
   are pinned in `tests/test_tripwires.py`.
7. **The microphone is single-speaker.** Events are labelled `unknown`, so
   extraction sees unlabelled text.
8. **The simulator is a ceiling.** Every eligible on-duty call goes to CRESS,
   there is no queue or travel time, and CRESS's own direct work is not
   modelled. Utilization counts only minutes inside the shift.
9. **The after-hours review group includes weekends.** It is the four clock
   hours after the rulebook's shift end, on every day.
10. **Display-only fields.** "Caller asked for CRESS", the stated location and
    the line a call came in on are recorded and shown; no rule reads them.
11. **No authentication.** Localhost only. See the threat model in
    [Architecture](ARCHITECTURE.md).

## Open items that need a person

- The licence file names one of the two authors as copyright holder. Changing
  it needs both authors' agreement.
- Repository settings (description, topics, secret scanning, branch
  protection) are set in GitHub, not in this tree.

## Future work

See the list in the [README](../README.md#future-work).
