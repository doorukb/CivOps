# Evaluations

These scripts call the real Claude extractor, so they cost money and live
outside `tests/`. Everything about them that can be checked for free (the case
files, the scoring functions, the keyword tripwire) is checked by pytest in
`tests/test_eval_cases.py`, `tests/test_eval_v2.py` and `tests/test_demo_fixtures.py`.

The full write-up, with what each number does and does not show, is in
[docs/EVALUATION.md](../../docs/EVALUATION.md).

## Status

| Set | Cases | Status | Result |
|-|-|-|-|
| `missed_escalations.py` (v1) | 27 disguised emergencies | Run once, 2026-11-15. Archived. | [`results/v1/`](results/v1/README.md) |
| `bias_pairs.py` (v1) | 11 pairs x 3 runs | Run once, 2026-11-15. Archived. | [`results/v1/`](results/v1/README.md) |
| `escalation_v2.py` | 40 emergencies, 18 screened controls, 7 unscreened controls, 5 hard negatives | **Pre-registered, not yet run** | none yet |
| `bias_pairs_v2.py` | 16 pairs x 3 runs, over 4 dialogue templates | **Pre-registered, not yet run** | none yet |
| `extraction_accuracy.py` | 40 hand-labelled calls | **Pre-registered, not yet run** | none yet |
| `record_demo_fixtures.py` | the 3 scripted demo calls | **Not yet run**; the fixture is a hand-written ideal extraction and says so | `fixtures/demo_scripts.json` |

"Pre-registered" means the cases, labels and scoring were committed before any
paid run, and must not be edited once results exist. To change a set, add a new
version next to it.

The v1 results are real but limited: no benign controls, and a bias design in
which routing could not vary. Read [`results/v1/README.md`](results/v1/README.md)
before quoting them.

## How to run

From `backend/`, with `ANTHROPIC_API_KEY` set (in `.env` or the environment).
Each paid command refuses to start without `--yes`, and refuses to overwrite an
existing results file.

```bash
# Free: validate the case files (also done by pytest)
python -m eval.escalation_v2 --check
python -m eval.bias_pairs_v2 --check
python -m eval.extraction_accuracy --check

# Paid: 70 + 96 + 40 + 3 = 209 extraction calls
python -m eval.escalation_v2 --yes
python -m eval.bias_pairs_v2 --yes
python -m eval.extraction_accuracy --yes
python -m eval.record_demo_fixtures --yes
```

Results go to `eval/results/v2/`. Every file starts with a `meta` block: model,
run date, SHA-256 of the extractor prompt, rulebook version, git commit and n.
After a run, commit the results file as it is, then update
`docs/EVALUATION.md` from it.

Three things to know before running:

- **The model is whatever `CIVOPS_EXTRACTION_MODEL` says** (default
  `claude-haiku-4-5`, the model v1 used). Results from different models are
  not comparable; the `meta` block records which one ran.
- **The prompt has changed since v1** (the transcript is now delimited, and a
  location field was added), and the pipeline now includes the hedge check. v2
  numbers describe the current pipeline, not the one v1 measured.
- **Temperature cannot be pinned to 0.** Current API versions reject sampling
  parameters, so extraction stays non-deterministic. `bias_pairs_v2` therefore
  reports a same-text noise floor next to every comparison.

## What each set measures

**`escalation_v2`** answers "does it catch emergencies *without* escalating
everything?" It reports, with Wilson 95% intervals:

- on 40 disguised emergencies (none contains a tripwire word): recognised by
  the model (`SAFETY-ESCALATION`), reached a human only because screening was
  incomplete (a weak catch), or routed to CRESS (missed). 13 of the 40 are
  dialogues where the screening questions *are* asked and some get a plain
  "no": those are the cases where a miss is possible, and they are also
  reported on their own;
- on 18 fully screened benign calls: false safety escalations, calls left
  incomplete, and calls that reached the expected rule;
- on 7 unscreened benign paragraphs: `SCREEN-INCOMPLETE` is the correct
  outcome, which shows how much of v1's "caught" was simply "not screened";
- on 5 hard negatives (a tripwire word in a harmless sense): the tripwire
  flags all 5 by design. This part is deterministic and free:
  `--check` prints it.

**`bias_pairs_v2`** answers "does one demographic detail change the extracted
facts or the routing?" Each pair is a dialogue with one answer left ambiguous
in severity, so the decision can land on `CRESS-001`, `SCREEN-INCOMPLETE` or
`SAFETY-ESCALATION`. It reports the A-vs-B difference rate next to the
same-text noise floor, per dimension and per template, plus the distribution
of decisions. If only one rule ID is observed it says the routing comparison
is uninformative instead of printing agreement. 16 pairs is a smoke test: it
cannot support "no bias found".

**`extraction_accuracy`** answers "how often is each extracted field right?"
It scores the pipeline's output against 40 hand-written labels and reports the
two errors that matter for safety separately: a reported concern that was lost
(true to false/unknown), and an unknown that was treated as "no".

**`record_demo_fixtures`** stores the model's raw proposal for the three
scripted calls so the demo is regression-tested offline.

All transcripts are fictional.
