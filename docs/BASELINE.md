# CivOps baseline: where we are against the scope

**Baseline date:** November 15, 2026. **Branch:** `new_features`. It starts from commit `0cb8e26` (live Deepgram transcription and call controls), plus the setup fixes listed at the end. **Last updated:** November 15, 2026, at commit `2066c94`.

This file compares the original scope (the HackUMass project plan) with what the code does now. The repository was checked directly. Claims from the build conversation were rerun where possible.

## Verified on a clean clone

| Check | Result |
|-|-|
| `python -m pytest tests/ -q` (Python 3.13, fresh venv from `requirements.txt`) | 134 passed, no paid API calls |
| `npm install && npm run build` | Builds without errors |
| `npm run lint` | Clean |
| Live paths (Deepgram mic → browser → Claude → rules) | Reported working by the developer. Not rerun here because they need API keys and a microphone. |
| Evaluations in `backend/eval/` | **Not run.** They make paid Claude calls. This file quotes no evaluation results. |

## Scope vs. achieved

✅ done · ⚠️ partial or a different approach · ❌ not started

### Must ship

| Scope item | Status | Notes |
|-|-|-|
| Rulebook in a version-controlled YAML file | ✅ | `backend/rules/dispatch.yaml` v0.1. Each rule has an ID, conditions, destination and source. |
| Rule unit tests | ✅ | `tests/test_rule_engine.py`, `tests/test_tripwires.py` |
| Exhaustive completeness check (every input combination matches exactly one rule) | ✅ | `tests/test_rulebook_completeness.py` runs 6 call types (including none) × 81 true/false/unknown safety patterns × 336 half-hours of a week = 163,296 inputs. It asserts that none returns `RULEBOOK-ERROR`, that only allowed destinations come out, that safety answers take precedence and that every rule fires. A missing timestamp isn't in the grid. One guard before the rules sends it to `CONTEXT-INCOMPLETE`. |
| Rule conditions for line type (911 or non-emergency) and caller asked for CRESS / no police | ❌ | Rules only use `eligible_call_type` and `on_duty`. `caller_requests_cress` is extracted and shown in Live Call as display-only. No rule reads it. |
| Console: extract facts, cite a rule, show the tripwire | ✅ | Live Call view: Claude extraction with evidence quotes, editable fields, rule ID shown on the decision card |
| Console: "play scripted call" mode (backup if the mic or Wi-Fi fails) | ✅ | `GET /scenarios`, `POST /scenarios/{id}/play` and a button per script in Live Call. Three scripts: routine wellbeing check, hidden knife (tripwire) and incomplete screening (`SCREEN-INCOMPLETE`). They replay through the same WebSocket path and need neither the mic nor Deepgram. |
| Hard tripwires on the raw transcript that the model can't clear | ✅ | `tripwires.py`, checked before the structured fields and rescreened live as the transcript arrives. The list now covers `attacking`, `stabbed`, `shots fired`, `shooting` and `threatening to …`. It is still lexical and doesn't understand negation. |
| Escalation goes to a human, never to police on its own | ✅ | Every safety path returns `human_review` |
| Replay audit sorted into the town's four review groups | ✅ | `/audit/demo` and `/audit/run`, plus the Monthly Audit view |
| Synthetic month matching LEAP's volumes and timing | ⚠️ | 250 calls. Times follow the illustrative hour/day weights shared in `leap_arrivals.py` (fitted to the brief's coverage table, not copied from LEAP). "Actual" dispatch uses its own named assumptions in `synthetic.py` (CRESS only weekdays 8–16, 25% referral, 3% misroute, 8% true and 5% unknown safety answers). Labeled `calibrated_to_leap=false`. |
| What-if simulator calibrated to LEAP | ⚠️ | SimPy simulation with on-duty and busy-team checks. `POST /simulation/compare` and the What-If view run `run_comparison`: 50 seeded replications on arrivals fitted to the coverage table, with mean and p10–p90 over a fixed horizon. Still missing: weights taken from LEAP's own tables and a Recharts chart. Every eligible on-duty call goes to CRESS, so results are a ceiling. `/simulation/run` still runs a single pass on supplied calls. |

### Should ship

| Scope item | Status | Notes |
|-|-|-|
| Live phone call into the console | ⚠️ | The laptop microphone with Deepgram live STT stands in for it. No Twilio. Single speaker (`unknown`). |
| Extraction every few seconds during the call | ⚠️ | Extraction runs once, automatically, when the call ends, and the operator can click "Extract with Claude" at any time. The tripwire (not Claude) rescreens the live transcript as it changes. |
| Bias audit on matched pairs of Suspicious calls | ❌ | `backend/eval/bias_pairs.py` is designed (11 pairs × 3 runs, with a noise floor), and `tests/test_eval_cases.py` checks the case data. It has not been run, so there are no results. |
| Missed-escalation evaluation (about 40 disguised emergencies, with a confidence interval) | ❌ | `backend/eval/missed_escalations.py` is designed (27 cases, Wilson 95% interval), and `tests/test_eval_cases.py` checks that no case uses a tripwire word. It has not been run, so there are no results. |

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
| Twilio, ngrok, recorded-call notice | ❌ | `twilio` was removed from `requirements.txt` until this is started. |
| pandas and NumPy | ⚠️ | NumPy is used by the simulator. pandas was never used and was removed from `requirements.txt`. |

## Known defects carried forward

These come from the handoff's §10 and §16, and the code confirms them:

1. **Start/stop races.** `/calls/start` returns before Deepgram connects. `/calls/end` returns before the final words arrive, and the UI then drops them because `callActiveRef` is already false.
2. **No call ID.** Late events from one call can land in the next. `/ws/transcript` sends every event to every client, and `/transcript/event` has no authentication.
3. **Stale extraction.** A Claude response that arrives after the transcript was edited overwrites the newer state.
4. **Overconfident negatives.** Claude can turn "I haven't seen any weapons" into `weapon_present=false`.
5. **Simulator utilization.** The denominator uses the span between the first and last call, and busy time past the end of a shift isn't counted.
6. **Audit replay skips tripwires.** `AuditRecord` has no transcript field.
7. **Fixed timestamp.** Live Call uses the hard-coded `2026-11-16T10:00-05:00` instead of the call's real time.

**Update (defects 1 and 2):** start/stop races and lost last words are addressed by `__call_started__` / `__call_ended__` / `__call_error__` markers, and the UI now waits for the end marker. Not yet tested against a real microphone. Call IDs are still not implemented, so the late-event-from-a-previous-call case is only covered by the one-session-at-a-time rule.

**Update (defect 3):** fixed. `LiveCall.tsx` bumps a version counter on every transcript or field edit and discards an extraction or evaluation response that comes back after one, with a notice to run it again.

**Update (defect 4):** still open. The extractor prompt asks for `false` only on an explicit denial, and the backend checks that the evidence quote appears in the transcript (ignoring speaker labels, case and spacing). The quote check proves the words exist, not that they support the value.

**Update (defect 5):** `simulate_incidents` accepts `horizon_start` / `horizon_end` (local dates, end exclusive), and `run_comparison` always passes them, so utilization uses the whole horizon. Without them it still falls back to the first-to-last-call span, which is what `/simulation/run` does today. Busy time past the end of a shift is still not counted (unchanged).

**Update (defect 6):** still open. `AuditRecord` now has an optional `transcript` field, but `audit_calls` doesn't pass it to the rule engine, so replay still skips the tripwire.

**Update (defect 7):** a different approach. The hidden hard-coded time is gone. The operator picks a visible simulated call time (Monday 2 PM, Monday 7:30 PM or Saturday 11 AM) that is sent with each evaluation. The call's real start time is still not used.

## Setup fixes made for this baseline

- Added `sounddevice` to `requirements.txt`. Before this, `tests/test_api.py` failed to import on a clean clone. Pinned the package versions that were tested together and removed a duplicate `deepgram-sdk[pytest]` entry.
- Removed unused packages from `requirements.txt`: `twilio`, `pandas`, `pydantic-settings`, `pytest-asyncio` (the tests use `asyncio.run`) and the unpinned `websockets` (`uvicorn[standard]` installs it). Removed the matching pytest-asyncio option from `pytest.ini`. Pinned `tzdata`, which pandas used to bring in. Without it, `zoneinfo` fails on Windows and 7 test files don't import on a clean clone.
- Added `backend/.env.example`.
- Added `.gitignore` patterns for local audio (`*.m4a`, `*.wav`, `*.mp3`).
- Extractor prompt: added a missing space that joined "instructions." and "Classify" into one word, and removed a duplicate `safety_fields` tuple.
- Wrote a README with run instructions for Windows, macOS and Linux, a demo-day command, scripted calls and the known limits.

## Plan for the next steps

The order puts demo reliability first, then the must-ship gaps, then the should-ship items.

| # | Step | Why | Size | Status |
|-|-|-|-|-|
| 1 | **Scripted call playback.** A backend endpoint replays a canned transcript as `TranscriptEvent`s through the same WebSocket path. Include three scripts: routine wellbeing check → CRESS, hidden knife → tripwire, and an incomplete call → `SCREEN-INCOMPLETE`. | Must-ship. It's the demo backup and needs neither the mic nor Deepgram. | S | ✅ |
| 2 | **Rulebook completeness test.** Use `itertools.product` over call types × safety values (T/F/None) × on duty × timestamp present, and assert exactly one rule ID each time and never `RULEBOOK-ERROR`. | Must-ship, and it's a strong talking point for judges | S | ✅ (missing timestamp covered by a guard, not the grid) |
| 3 | **Call ID and stop drain.** `/calls/start` returns a `call_id` that is added to every event. The backend sends `started` and `stopped` events, and the UI stops accepting text only on `stopped`. | Fixes defects 1 and 2: lost last words and calls mixing | M | ⚠️ markers done, no call ID |
| 4 | **Stale-extraction guard.** A transcript revision counter or `AbortController` in `LiveCall.tsx` | Fixes defect 3 | S | ✅ |
| 5 | **Use the real call timestamp.** Stamp the call's start time and show it in the UI. | Fixes defect 7, so the CRESS-vs-follow-up demo is honest | S | ⚠️ visible simulated time instead |
| 6 | **Grow the tripwire list.** Add `attacking`, `stabbed`, `shot`, `threatening`, and so on, with tests. | Closes a safety gap in the demo script | S | ✅ |
| 7 | **Simulator on a seeded 30-day month.** Shape arrivals by LEAP's hour-of-day and day-of-week patterns, use a fixed horizon, run N Monte Carlo replications with p10/p50/p90, and add a Recharts comparison chart. | Must-ship "calibrated" claim | M | ⚠️ replications and bands done, no chart, weights not from LEAP |
| 8 | **Shape the audit generator by LEAP's timing patterns.** | Must-ship | S | ⚠️ shaped by weights fitted to the coverage table |
| 9 | **Evaluation scripts.** A hand-written disguised-emergency set with a Wilson confidence interval, and matched Suspicious pairs for the bias audit. Cache the outputs so tests stay offline. | Should-ship | M | ⚠️ scripts written, not run |
| 10 | **Twilio Media Streams.** Only if steps 1–4 are done. | Should-ship, highest risk | L | ❌ |

SQLite override logging, the location field and the stretch items stay deferred until the steps above are done.
