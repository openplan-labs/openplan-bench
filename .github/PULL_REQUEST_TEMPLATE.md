## What this changes

<!-- One or two sentences. If it adds a suite, say what question the suite
     answers — "more instances" is not a reason. -->

## Type

- [ ] New adapter
- [ ] New or changed suite
- [ ] Harness / CLI / site change
- [ ] Committed results from a run
- [ ] Documentation or a methodology correction

## Checks

- [ ] `ruff check .` passes
- [ ] `pytest` passes
- [ ] Nothing under `results/` was hand-edited

## If this adds an adapter

- [ ] `available()` returns a reason instead of raising when the backend is absent
- [ ] The backend is imported inside `run()`, never at module scope
- [ ] Validity is checked independently — not taken from the planner's own claim
- [ ] Metrics the backend does not report are left `None`, not zeroed
- [ ] `timeout_s` is passed down where the backend has its own budget knob
- [ ] An extra was added in `pyproject.toml`, and a suite exercises it

## If this commits results

- [ ] The machine they were measured on:
- [ ] No existing dated results file was overwritten
- [ ] Runs that timed out or errored are present in the file, not filtered out
