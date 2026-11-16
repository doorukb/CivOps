# Evaluation

Every number on this page comes from a file in this repository. All evaluation
data is synthetic and hand-written. Every set is small, so intervals are wide,
and nothing here describes performance on real calls.

## At a glance

| What | State | Where |
|-|-|-|
| Rulebook completeness (163,296 inputs) | Verified on every commit | `backend/tests/test_rulebook_completeness.py` |
| Worst-case behaviour of the deterministic checks | Verified on every commit | `backend/tests/test_extractor.py`, `test_one_way_autonomy.py`, `test_eval_v2.py` |
| The three scripted calls, replayed offline | Verified on every commit, against a **hand-written** extraction | `backend/tests/test_demo_fixtures.py` |
| Disguised emergencies, v1 (27 cases) | Run once, 2026-11-15. Archived | `backend/eval/results/v1/missed_escalations.json` |
| Matched pairs, v1 (11 pairs x 3 runs) | Run once, 2026-11-15. Archived | `backend/eval/results/v1/bias_pairs.json` |
| Escalation v2 (40 emergencies + 30 controls) | **Pre-registered, not yet run** | `backend/eval/escalation_v2.py` |
| Matched pairs v2 (16 pairs x 3 runs) | **Pre-registered, not yet run** | `backend/eval/bias_pairs_v2.py` |
| Extraction accuracy (40 labelled calls) | **Pre-registered, not yet run** | `backend/eval/extraction_accuracy.py` |

"Pre-registered" means the cases, the labels and the scoring code were
committed before any paid run, and are not to be edited once results exist.

## What is verified without a model

These hold whatever the model does, and are checked by the test suite.

**The rulebook gives exactly one answer for every input.** 6 call types x 81
screening patterns x 336 half-hours = 163,296 inputs. No input falls through,
only CRESS, CRESS follow-up or human review can come out, a "yes" always
escalates, and CRESS is reachable only with four "no" answers.

**An obedient model cannot clear a call.** Four prompt-injection transcripts
are tested by assuming the worst: the model does what the transcript says and
returns "all clear" with invented quotes. Every answer is discarded by the
evidence check, the call stays `SCREEN-INCOMPLETE`, and a safety word in the
transcript still wins.

**A hedged "no" does not count.** The hedge check resets a "no" to unknown
when its sentence, or the one after it, is hedged. One test takes all eight
hedged denials in the extraction gold set, assumes a model answered "no" to
each while quoting the caller, and asserts every one is reset.

**A CRESS recommendation built on the model's word is provisional.** For
every call type and every half-hour of the week, with all four answers
model-proposed "no": every recommendation that leaves the dispatcher is
provisional, and the server refuses to store it as confirmed.

## v1 results (archived)

Both were run once on 2026-11-15 with `claude-haiku-4-5`, using the extractor
prompt as it was then (before the transcript was delimited and before the
hedge check existed). The files record no model, date or prompt hash; those
facts come from git history. Recomputed from the archived files:

### Disguised emergencies: 27 cases, none containing a tripwire word

| Outcome | Cases | Wilson 95% |
|-|-|-|
| Recognised by the model (`SAFETY-ESCALATION`) | 22 of 27 = 81% | 63% to 92% |
| Human review only because screening was incomplete | 5 of 27 | |
| Routed to CRESS or CRESS follow-up (missed) | 0 of 27 = 0% | 0% to 12% |

Why this is weaker than "27 of 27 caught":

- **No benign controls.** A system that sends everything to human review
  scores 27 of 27. Without controls, the run cannot tell caution from
  recognition.
- **Unscreened paragraphs always reach a human.** Each case is one caller
  paragraph with no dispatcher questions, so unasked questions come back
  unknown and the call goes to `SCREEN-INCOMPLETE` whether it is dangerous or
  not. Five cases were "caught" this way and no other.

The defensible statement is: *on 27 hand-written synthetic cases, the model
recognised the danger in 22; none was routed to CRESS; over-escalation was not
measured.*

### Matched pairs: 11 Suspicious-call pairs, 3 runs each

| Comparison | Fields identical | Decision identical |
|-|-|-|
| Version A vs version B, same run (33) | 26 = 79% (Wilson 95%: 62% to 89%) | 33 of 33 |
| Same text, different runs: the noise floor (66) | 52 = 79% (67% to 87%) | 66 of 66 |

Why "33 of 33 decisions matched" means nothing here: all 66 extractions ended
at `human_review / SCREEN-INCOMPLETE`. `injury` and `immediate_danger` were
unknown in 66 of 66, because the templates contain no screening answers. The
routing layer never reached a stage where a demographic detail could matter,
so agreement was guaranteed by the design.

On fields: agreement between versions equals the noise floor, and all seven
differences are one field (`violence`) flipping between unknown and "no". The
run cannot separate a demographic effect from run-to-run variation.

The defensible statement is: *an extraction-variability smoke test; routing
was constant by construction, so no conclusion about routing or bias can be
drawn.* It is not a bias audit and does not support "no bias found".

## v2 design (pre-registered, not yet run)

### Escalation v2: emergencies and controls

`backend/eval/data/escalation_v2.yaml`, 70 cases:

| Group | n | Purpose |
|-|-|-|
| Emergencies | 40 | The 27 v1 paragraphs, reused unchanged, plus 13 **dialogues** in which the screening questions are asked and some get a plain "no". These 13 are where a miss is actually possible, and are also reported on their own. |
| Screened controls | 18 | Benign calls with all four questions asked and plainly denied. Each names the rule an ideal extraction should reach. A safety escalation here is a false escalation. |
| Unscreened controls | 7 | Benign paragraphs. `SCREEN-INCOMPLETE` is correct, which shows how much of v1's "caught" was "not screened". |
| Hard negatives | 5 | Benign calls with a tripwire word in a harmless sense ("flu shot", "splitting firewood with an axe"). |

It reports, each with a Wilson interval: recognised / incomplete-only / missed
on emergencies; false escalation / left incomplete / reached the expected rule
on controls; and how many misses would have been provisional in the console.

One part is deterministic and already known, because the tripwire needs no
model (`python -m eval.escalation_v2 --check`):

| Group | Tripwire flagged |
|-|-|
| Emergencies | 0 of 40 (by design: the cases avoid its words) |
| Screened controls | 0 of 18 |
| Unscreened controls | 0 of 7 |
| Hard negatives | 5 of 5 (by design: this is the cost of matching words) |

### Matched pairs v2: dialogues where routing can differ

`backend/eval/data/bias_pairs_v2.yaml`: 16 pairs over 4 templates, 3 runs.
Each template is a dispatcher/caller dialogue with all four questions asked.
In the `clear` template all four get a plain "no" (a correct extraction
reaches `CRESS-001`). In the other three, exactly one answer is ambiguous in
severity, so the decision can land on `CRESS-001`, `SCREEN-INCOMPLETE` or
`SAFETY-ESCALATION`. Templates avoid pronouns, so a pair changes one detail.

It reports the A-vs-B difference rate for decisions and for fields, next to
the same-text noise floor, per dimension and per template, with the
distribution of decisions. If only one rule ID is observed, it reports the
routing comparison as uninformative instead of printing agreement. Sixteen
pairs is still a smoke test.

### Extraction accuracy

`backend/eval/data/extraction_gold.yaml`: 40 calls with hand-written labels
for call type, the four screening answers and "caller asked for CRESS", in
seven categories (plain, hedged denials, dispatcher-question traps, explicit
positives, unlabelled microphone-style text, partial screening, CRESS
requests). It scores the pipeline's output, not the raw model output, and
reports per-field accuracy with the two errors that matter for safety on their
own lines: a reported concern that was lost, and an unknown that became "no".

### Running them

See [`backend/eval/README.md`](../backend/eval/README.md). About 209 extraction
calls in total. Each results file starts with a `meta` block (model, run date,
SHA-256 of the extractor prompt, rulebook version, git commit, n). After a
run, commit the results file unchanged and update this page from it.

## Limits that apply to everything here

- **Synthetic and hand-written.** One author's idea of what calls sound like.
- **Small.** With n = 27, zero misses still leaves an upper bound near 12%.
- **Not deterministic.** Current API versions do not accept a temperature, so
  the same transcript can extract differently on two runs. The matched-pair
  evaluation measures that noise instead of assuming it away.
- **One model, one prompt.** Results belong to the model and prompt recorded
  in their `meta` block. The default model is still `claude-haiku-4-5`, the
  one v1 used; changing `DESPATCH_EXTRACTION_MODEL` means re-running before
  quoting any number.
- **v1 and v2 measure different pipelines.** v2 runs through the delimited
  prompt and the hedge check; v1 did not.
