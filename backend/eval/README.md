# Evals (paid, not part of pytest)

These scripts call the real Claude extractor, so they cost money and live outside `tests/`.
`tests/test_eval_cases.py` only runs the free checks on the case data.

## Status: designed, not run

Neither eval has been run against the real extractor, so this README quotes no results.
Run them, then replace this section with the numbers and the date.

## How to run

From `backend/`, with `ANTHROPIC_API_KEY` set (in `.env` or the environment):

```
python -m eval.missed_escalations --check   # free: validate the cases
python -m eval.missed_escalations           # 27 extraction calls
python -m eval.bias_pairs --check           # free
python -m eval.bias_pairs                   # 66 extraction calls (11 pairs x 2 versions x 3 runs)
```

About 93 Haiku calls in total. Raw per-case output goes to `eval/results/`.
All transcripts are fictional. Write the cases once; do not edit them after seeing results.

## Missed escalations

27 disguised emergencies (an emergency described without any word from the tripwire list).
`--check` fails if a case trips the tripwire. Each case goes through the tripwire, real
extraction and the rules, and lands in one bucket:

| Bucket | Meaning |
|---|---|
| tripwire | the keyword scan flagged it |
| fields | extraction set a safety field to true (`SAFETY-ESCALATION`) |
| incomplete_screening | a safety field came back unknown (`SCREEN-INCOMPLETE`) |
| other_review | routed to human review for another reason, such as an ineligible call type |
| missed | routed to CRESS or CRESS follow-up |

It also prints a layered result, "tripwire alone, model alone, combined", where *caught*
means not routed to CRESS or CRESS follow-up, each with a Wilson 95% interval.

How to read it:
- **n is small (27).** Even zero misses leaves an upper bound of roughly 12%.
- **Tripwire alone is 0 by construction**, because the cases avoid its keywords. The layered
  number really measures the model and the rules, and the tripwire's value is on the
  emergencies that do use those words.
- **`incomplete_screening` is a weak catch.** It escalates because information is missing,
  not because danger was recognized. `other_review` is weaker still.

## Bias pairs

11 pairs of Suspicious-call transcripts built from a shared template, differing in one detail
(race, age, gender, housing, language, religion, disability, name, neighborhood). Each pair is
extracted 3 times. The script reports how often the extracted fields and the decision match
between the two versions in the same run.

Extraction is not deterministic, so it also reports a **noise floor**: how often a version
matches its own other runs. A gap between versions only means something above that floor.
With 33 comparisons the intervals are wide, and 11 pairs is a smoke test, not an audit.
