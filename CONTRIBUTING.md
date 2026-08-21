# Contributing

Glad you showed up. This repository has three kinds of contribution and they
have quite different bars.

## 1. A new adapter

The most useful thing you can add. The full walkthrough is in
[the README](README.md#adding-a-planner); the short version is one module in
`openplan_bench/adapters/`, one line in the registry, one extra in
`pyproject.toml`, and one suite that exercises it.

What a review will look for:

- **`available()` never raises.** A machine without your backend must still
  produce `not-installed` rows. Import the backend inside `run()`, never at
  module scope.
- **Validity is checked independently.** Do not set `valid=True` because the
  planner said so. Replay the plan, or re-check the paths.
- **Unreported metrics stay `None`.** A `0` in `expanded` that means "not
  measured" is worse than a blank cell.
- **No timing, retrying or budget logic in the adapter.** The harness owns
  those so that every backend is measured identically. Do pass `timeout_s`
  down when your backend has its own budget knob — a planner that stops cleanly
  reports much better statistics than one we have to kill.

## 2. A new suite

Suites live in `suites/` and the filename must match the `name:` key.
`tests/test_suites_are_valid.py` checks that every suite parses, names real
adapters, and plans at least one run.

Before opening the PR, say in the description **what question the suite
answers**. "More instances" is not a reason; "the density sweep shows where CBS
stops terminating, which the agent-count sweep hides" is.

Rules the tests enforce:

- MAPF groups use at least three seeds. A median over two numbers is a mean.
- No budget above two minutes — a suite nobody can run in CI is a suite that
  rots.
- Classical suites may use one seed, since planning here is deterministic, but
  then `repetitions` is the only thing giving the timing more than one sample.
  A classical group with `seeds x repetitions == 1` fails the tests unless the
  suite is named in `SINGLE_SAMPLE_CLASSICAL` and listed under known
  limitations in the README — a median over one number is that number, and the
  dashboard has to say so above the table.
- Every suite must set `timeout_s` and `memory_limit_mb`. They are stamped onto
  every row and the dashboard reads the published budget off the rows, so a
  table can never be printed without the conditions it was measured under.

## 3. A correction

**If you think a number is wrong or a caption overclaims, file it.** That is
not a nuisance issue, it is the most valuable kind of report this project gets.
A benchmark's only asset is that people believe it.

Include the suite, the row, and what you think it should say.

## Working on the harness

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[all,dev]'
git clone https://github.com/openplan-labs/pddl-examples corpus/pddl-examples

pytest
ruff check .
```

The test suite runs entirely against the `fake` adapter, so it is fast and
deterministic and needs no planner installed. Keep it that way: if a test needs
`jupyddl` or `pymapf` to be present, it belongs in a suite, not in `tests/`.

The behaviours worth writing tests for are the failure behaviours. Anyone can
write a harness that records a success; this one has to record a planner that
hangs inside a C extension, one that eats all the memory, one that returns an
invalid plan, and one that is not installed at all.

## Results files

**Do not hand-edit anything under `results/`.** They are evidence. If a run
produced numbers you do not believe, re-run it and commit the new dated file
next to the old one — history is never overwritten, and a suspicious result
that turned out to be real is worth having on record.

Committing results from your own machine is fine and welcome. Say what machine
in the PR description; the rows carry it too.

## Style

- `ruff check .` must pass. Line length 88.
- Imperative docstrings: "Return the plan", not "Returns the plan".
- Comments explain *why*, not *what*. The load-bearing ones in this codebase
  are the ones justifying a measurement decision — keep writing those.
- Name papers when an algorithm first appears. "A\*" alone is ambiguous.
- No emoji as section markers.

## Code of Conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
