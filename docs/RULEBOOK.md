# Rulebook

The whole routing policy is one file: [`backend/rules/dispatch.yaml`](../backend/rules/dispatch.yaml).
The language model never reads it. Plain code in
[`rule_engine.py`](../backend/app/services/rule_engine.py) walks it in a fixed
order and returns the first outcome that applies.

**It is illustrative.** The schedule, the eligible call types, the screening
questions and every rule are assumptions made for this project. Each `source`
field says so. Nothing here is an official protocol of any town or service.

## Evaluation order

| Stage | Block in the YAML | Fires when | Rule ID | Destination |
|-|-|-|-|-|
| 1 | `screening.tripwire` | the raw transcript contains a tripwire word | `TRANSCRIPT-TRIPWIRE` | human review |
| 2 | `screening.escalation` | any safety field is `true` | `SAFETY-ESCALATION` | human review |
| 3 | `screening.incomplete` | any safety field is unknown | `SCREEN-INCOMPLETE` | human review |
| 4 | `screening.context_incomplete` | call type or timestamp is missing, or the timestamp has no UTC offset | `CONTEXT-INCOMPLETE` | human review |
| 5 | `rules` | exactly one rule's conditions match | see below | see below |

The order is the safety argument: a later stage cannot undo an earlier one.
The tripwire comes first so that nothing extracted by the model can clear it.
"Unknown" comes before eligibility so that an unanswered question is never
treated as "no".

## The rules (v0.2)

| ID | Conditions | Destination | Source |
|-|-|-|-|
| `CRESS-001` | eligible call type, on duty | `cress` | Illustrative eligibility assumption |
| `CRESS-002` | eligible call type, off duty | `cress_followup` | Illustrative follow-up assumption |
| `REVIEW-001` | call type not eligible | `human_review` | Illustrative project assumption |

Eligible call types: `wellbeing_check`, `disturbance`, `suspicious`.
Schedule: Monday to Friday, 8:00 to 16:00, America/New_York.

If no rule matches, or two rules of the same priority match, the engine
returns `RULEBOOK-ERROR` → human review. The completeness test shows this
cannot happen with the shipped file.

## Schema

```yaml
version: "0.2"

screening:
  safety_fields: [weapon_present, violence, injury, immediate_danger]
  tripwire:            {id, destination, reason, source}   # stage 1
  escalation:          {id, destination, reason, source}   # stage 2
  incomplete:          {id, destination, reason, source}   # stage 3
  context_incomplete:  {id, destination, reason, source}   # stage 4

schedule:
  timezone: America/New_York
  weekdays: [0, 1, 2, 3, 4]   # the days a shift STARTS, Monday = 0
  start_hour: 8               # 0 to 23
  end_hour: 16                # 1 to 26; above 24 runs past midnight (26 = 2 AM)

eligible_call_types: [wellbeing_check, disturbance, suspicious]

rules:
  - id: CRESS-001
    priority: 1               # lower number wins
    conditions:               # facts this rule tests; omit one to ignore it
      eligible_call_type: true
      on_duty: true
    destination: cress
    reason: "..."
    source: "..."
```

The file is validated at load ([`rulebook.py`](../backend/app/rulebook.py)).
These all fail with a clear error before the server starts:

- an unknown key anywhere (for example a misspelled condition, which would
  otherwise silently never match);
- a duplicate rule ID, an unknown destination, call type or time zone;
- a schedule that ends before it starts, or a shift past midnight that
  overlaps the next day's shift;
- a missing `source`;
- **a safety outcome (stages 1 to 4) whose destination is not `human_review`;**
- **a rule whose destination is `police`, `fire_ems` or `crisis`.**

The last two are the project's invariants, enforced on the file itself:
every safety path ends with a person, and nothing routes to police on its own.

## Destinations

| Value | Can a rule produce it? | Used for |
|-|-|-|
| `cress` | yes | community responders, now |
| `cress_followup` | yes | community responders, when next on duty |
| `human_review` | yes | a human dispatcher decides |
| `police`, `fire_ems`, `crisis` | **no (reserved)** | describing what dispatch *actually* did in audit records, and what a dispatcher chose in an override |

## Facts that are recorded but not used by any rule

| Field | Where it appears | Why no rule reads it |
|-|-|-|
| `caller_requests_cress` | extracted, shown in Live Call | How a caller's request should weigh against screening is a policy question for the people who own the policy. Shown for context only. |
| `source_line` (`911` or `non_emergency`) | synthetic audit records; the audit breaks missed referrals down by line | Same reason. A test asserts that the line never changes a recommendation. |
| `location` | extracted, shown in Live Call | Display only. No maps, no address history. |

## The "provisional" flag

A stage-5 recommendation that sends a call away from the dispatcher
(`cress` or `cress_followup`) is marked `provisional` while any "no" among the
safety fields came from the model and has not been confirmed by a person. The
destination and the rule ID do not change. The server will not record such a
recommendation as confirmed. A model-proposed "yes" needs no confirmation: it
only raises urgency.

## Adding or changing a rule

1. Edit `backend/rules/dispatch.yaml`. Give the rule a unique `id`, a
   `priority`, `conditions`, a routable `destination`, a `reason` and a
   `source`. Bump `version`.
2. A new *condition* (a fact that rules can test) also needs: a field on
   `Conditions` in `rulebook.py`, and the fact computed in
   `evaluate_incident()`.
3. Run `python -m pytest tests/test_rulebook_completeness.py tests/test_rulebook_schema.py`.
   - If the new condition depends on an input that the grid does not vary,
     add that input to the grid and update the size constants and this page.
     Never loosen an assertion to make the test pass.
   - `test_every_rule_fires` fails if a rule can never be reached.
4. If the rule changes what the demo shows, update
   `tests/test_demo_fixtures.py` and [the demo script](DEMO.md).

## What the completeness test covers

`tests/test_rulebook_completeness.py` evaluates every combination of:

- 6 call types (the five, plus none),
- 81 screening patterns (yes / no / unknown for each of four questions),
- 336 half-hours of one week,

which is 6 x 81 x 336 = **163,296** inputs, and asserts that:

- no input returns `RULEBOOK-ERROR`;
- only `cress`, `cress_followup` or `human_review` ever comes out;
- any "yes" gives `SAFETY-ESCALATION`, and otherwise any unknown gives
  `SCREEN-INCOMPLETE`;
- `cress` is reached only when all four answers are "no";
- every rule and every safety outcome fires at least once;
- every decision carries a source and the rulebook version.

A missing timestamp is outside the grid and is covered by a separate guard
test. The tripwire needs a transcript and is tested on its own.

## The tripwire list

Six categories (weapon, violence, injury, medical, self-harm, threat), matched
as whole words, case-insensitively, on the raw transcript
([`tripwires.py`](../backend/app/services/tripwires.py)).

- It does not understand negation: "he does not have a gun" still flags. A
  flag costs a human look; a miss costs more.
- Bare `weapon`, `violent`, `threat`, `hurt`, `injured` and `danger` are
  deliberately not on the list. The dispatcher's own questions contain them,
  and callers repeat them in plain denials ("No, there are no weapons"), so
  they would flag every fully screened routine call. They match only inside a
  phrase a question does not use ("pulled a weapon", "threatened her").
- Bare `shot`, `pills`, `bat` and `hammer` are also left out ("flu shot",
  "sleeping pills"). They match in a telling phrase ("was shot", "took too
  many pills", "he has a bat").
- Known false positives are pinned in `tests/test_tripwires.py`, for example
  "my neighbor has a hammer going at 6 AM" and "flu shot at the pharmacy".
- It will miss an emergency described without any listed word. That gap is
  what the model's screening answers and the disguised-emergency evaluation
  are for.
