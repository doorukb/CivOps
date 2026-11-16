# v1 results (archived, 2026-11-15)

These two files are the first and only run of the v1 evaluations. They are kept
unchanged as history. Do not edit them and do not quote them without the
caveats below. New runs use the v2 sets (`eval/escalation_v2.py`,
`eval/bias_pairs_v2.py`, `eval/extraction_accuracy.py`).

| | |
|-|-|
| Run date | 2026-11-15 (committed in `db0a4c7`) |
| Model | `claude-haiku-4-5` (hard-coded in the extractor at the time) |
| Extractor prompt | the prompt at commit `73d2998`, before the transcript was delimited and before the hedge check existed |
| Recorded in the files | nothing: v1 results carry no model, date, prompt hash or commit. The values above come from git history. Every later results file has a `meta` block. |

## `missed_escalations.json`: 27 disguised emergencies

| Outcome | Cases |
|-|-|
| `SAFETY-ESCALATION` (the model set a safety answer to true) | 22 of 27 = 81% (Wilson 95%: 63% to 92%) |
| `SCREEN-INCOMPLETE` (a safety answer came back unknown) | 5 of 27 |
| Routed to CRESS or CRESS follow-up (missed) | 0 of 27 (Wilson 95%: 0% to 12%) |

What it does **not** show:

- **There are no benign controls.** A system that escalates every call also
  scores 27 of 27, so this run says nothing about over-escalation.
- **Five of the 27 were not recognised as dangerous.** They went to human
  review only because screening was incomplete, and screening is always
  incomplete for these cases: each one is a single caller paragraph with no
  dispatcher questions, so unasked questions come back unknown for *any* such
  transcript, benign or not. The stricter figure is 22 of 27.

## `bias_pairs.json`: 11 matched pairs x 3 runs

| Comparison | Fields match | Decision matches |
|-|-|-|
| Version A vs version B, same run (33) | 26 of 33 = 79% (Wilson 95%: 62% to 89%) | 33 of 33 |
| Same text, different runs: the noise floor (66) | 52 of 66 = 79% | 66 of 66 |

What it does **not** show:

- **The routing comparison is uninformative.** All 66 extractions ended at
  `human_review / SCREEN-INCOMPLETE`: `injury` and `immediate_danger` were
  unknown in 66 of 66, because the templates contain no screening answers.
  Routing never reached a stage where a demographic detail could change the
  outcome, so "33 of 33 decisions matched" is true by construction.
- Field agreement between versions (79%) equals the same-text noise floor
  (79%). All seven A-vs-B differences are one field (`violence`) flipping
  between unknown and false. This run cannot separate a demographic effect
  from ordinary run-to-run variation.

Read it as an extraction-variability smoke test. It is not a bias audit, and it
does not support "no bias found".
