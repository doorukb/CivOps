# CivOps baseline: where we are against the scope

**Baseline date:** November 15, 2026. **Branch:** `new_features`. It starts from commit `0cb8e26` (live Deepgram transcription and call controls), plus the setup fixes listed at the end.

This file compares the original scope (the HackUMass project plan) with what the code does now. The repository was checked directly. Claims from the build conversation were rerun where possible.

## Verified on a clean clone

| Check | Result |
|-|-|
| `python -m pytest tests/ -q` (Python 3.13) | 43 passed, no paid API calls |
| `npm ci && npm run build` | Builds without errors |
| `npm run lint` | Clean |
| Live paths (Deepgram mic → browser → Claude → rules) | Reported working by the developer. Not rerun here because they need API keys and a microphone. |

## Scope vs. achieved

✅ done · ⚠️ partial or a different approach · ❌ not started

### Must ship

| Scope item | Status | Notes |
|-|-|-|
| Rulebook in a version-controlled YAML file | ✅ | `backend/rules/dispatch.yaml` v0.1. Each rule has an ID, conditions, destination and source. |
| Rule unit tests | ✅ | `tests/test_rule_engine.py`, `tests/test_tripwires.py` |
| Exhaustive completeness check (every input combination matches exactly one rule) | ❌ | The engine returns `RULEBOOK-ERROR` at runtime if no rule or several rules match, but no test enumerates every combination. |
| Rule conditions for line type (911 or non-emergency) and caller asked for CRESS / no police | ❌ | Rules only use `eligible_call_type` and `on_duty`. `caller_requests_cress` is extracted but never used. |
| Console: extract facts, cite a rule, show the tripwire | ✅ | Live Call view: Claude extraction with evidence quotes, editable fields, rule ID shown on the decision card |
| Console: "play scripted call" mode (backup if the mic or Wi-Fi fails) | ❌ | Not built. The only inputs are typing and the live mic. |
| Hard tripwires on the raw transcript that the model can't clear | ✅ | `tripwires.py`, checked before the structured fields. The word list is small (`attacking` is missing) and it doesn't understand negation. |
| Escalation goes to a human, never to police on its own | ✅ | Every safety path returns `human_review` |
| Replay audit sorted into the town's four review groups | ✅ | `/audit/demo` and `/audit/run`, plus the Monthly Audit view |
| Synthetic month matching LEAP's volumes and timing | ⚠️ | 250 calls with uniformly random types, times and past destinations. Labeled `calibrated_to_leap=false`. |
| What-if simulator calibrated to LEAP | ⚠️ | SimPy simulation with on-duty and busy-team checks. It runs on 9 hard-coded calls, makes a single run (no ranges), has no LEAP calibration and doesn't reproduce the coverage table. |

### Should ship

| Scope item | Status | Notes |
|-|-|-|
| Live phone call into the console | ⚠️ | The laptop microphone with Deepgram live STT stands in for it. No Twilio. Single speaker (`unknown`). |
| Extraction every few seconds during the call | ⚠️ | The operator clicks "Extract with Claude" by hand |
| Bias audit on matched pairs of Suspicious calls | ❌ | |
| Missed-escalation evaluation (about 40 disguised emergencies, with a confidence interval) | ❌ | |

### Stretch

| Scope item | Status |
|-|-|
| Conformal-prediction abstention | ❌ |
| Caller-facing voice intake | ❌ |

### Infrastructure in the scope

| Item | Status | Notes |
|-|-|-|
| SQLite log of calls, decisions and overrides (with reasons) | ❌ | Everything is in memory. Overrides change the fields but aren't logged. |
| Recharts charts | ❌ | The Audit and What-If views use metric cards and tables |
| Location field in the extraction form | ❌ | |
| Twilio, ngrok, recorded-call notice | ❌ | |
| pandas and NumPy | ⚠️ | Installed but not used |

## Known defects carried forward

These come from the handoff's §10 and §16, and the code confirms them:

1. **Start/stop races.** `/calls/start` returns before Deepgram connects. `/calls/end` returns before the final words arrive, and the UI then drops them because `callActiveRef` is already false.
2. **No call ID.** Late events from one call can land in the next. `/ws/transcript` sends every event to every client, and `/transcript/event` has no authentication.
3. **Stale extraction.** A Claude response that arrives after the transcript was edited overwrites the newer state.
4. **Overconfident negatives.** Claude can turn "I haven't seen any weapons" into `weapon_present=false`.
5. **Simulator utilization.** The denominator uses the span between the first and last call, and busy time past the end of a shift isn't counted.
6. **Audit replay skips tripwires.** `AuditRecord` has no transcript field.
7. **Fixed timestamp.** Live Call uses the hard-coded `2026-11-16T10:00-05:00` instead of the call's real time.

**Update:** defects 1 and 2 (start/stop races, last words lost) are addressed by `__call_started__` / `__call_ended__` / `__call_error__` markers, and the UI now waits for the end marker. Scripted calls (`/scenarios`) and `/calls/screen` exist. Not yet tested against a real microphone. Call IDs are still not implemented, so the late-event-from-a-previous-call case is only covered by the one-session-at-a-time rule.

## Setup fixes made for this baseline

- Added `sounddevice` to `requirements.txt`. Before this, `tests/test_api.py` failed to import on a clean clone. Pinned the package versions that were tested together and removed a duplicate `deepgram-sdk[pytest]` entry.
- Added `backend/.env.example`.
- Added `.gitignore` patterns for local audio (`*.m4a`, `*.wav`, `*.mp3`).
- Extractor prompt: added a missing space that joined "instructions." and "Classify" into one word, and removed a duplicate `safety_fields` tuple.
- Wrote a README with run instructions.

## Plan for the next steps (not started)

The order puts demo reliability first, then the must-ship gaps, then the should-ship items.

| # | Step | Why | Size |
|-|-|-|-|
| 1 | **Scripted call playback.** A backend endpoint replays a canned transcript as `TranscriptEvent`s through the same WebSocket path. Include three scripts: routine wellbeing check → CRESS, hidden knife → tripwire, and an incomplete call → `SCREEN-INCOMPLETE`. | Must-ship. It's the demo backup and needs neither the mic nor Deepgram. | S |
| 2 | **Rulebook completeness test.** Use `itertools.product` over call types × safety values (T/F/None) × on duty × timestamp present, and assert exactly one rule ID each time and never `RULEBOOK-ERROR`. | Must-ship, and it's a strong talking point for judges | S |
| 3 | **Call ID and stop drain.** `/calls/start` returns a `call_id` that is added to every event. The backend sends `started` and `stopped` events, and the UI stops accepting text only on `stopped`. | Fixes defects 1 and 2: lost last words and calls mixing | M |
| 4 | **Stale-extraction guard.** A transcript revision counter or `AbortController` in `LiveCall.tsx` | Fixes defect 3 | S |
| 5 | **Use the real call timestamp.** Stamp the call's start time and show it in the UI. | Fixes defect 7, so the CRESS-vs-follow-up demo is honest | S |
| 6 | **Grow the tripwire list.** Add `attacking`, `stabbed`, `shot`, `threatening`, and so on, with tests. | Closes a safety gap in the demo script | S |
| 7 | **Simulator on a seeded 30-day month.** Shape arrivals by LEAP's hour-of-day and day-of-week patterns, use a fixed horizon, run N Monte Carlo replications with p10/p50/p90, and add a Recharts comparison chart. | Must-ship "calibrated" claim | M |
| 8 | **Shape the audit generator by LEAP's timing patterns.** | Must-ship | S |
| 9 | **Evaluation scripts.** A hand-written disguised-emergency set with a Wilson confidence interval, and matched Suspicious pairs for the bias audit. Cache the outputs so tests stay offline. | Should-ship | M |
| 10 | **Twilio Media Streams.** Only if steps 1–4 are done. | Should-ship, highest risk | L |

SQLite override logging, the location field and the stretch items stay deferred until the steps above are done.
