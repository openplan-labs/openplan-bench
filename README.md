<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/openplan-labs/branding/main/assets/logo/mark-dark.svg">
  <img src="https://raw.githubusercontent.com/openplan-labs/branding/main/assets/logo/mark-accent.svg" width="44" alt="OpenPlan Labs">
</picture>

# openplan-bench

One harness, one problem set, one results schema for every planner in
[OpenPlan Labs](https://github.com/openplan-labs). It runs
[`jupyddl`](https://github.com/openplan-labs/PythonPDDL) over classical PDDL
instances and [`pymapf`](https://github.com/openplan-labs/pymapf) /
[`cuda-planning`](https://github.com/openplan-labs/cuda-planning) over
generated multi-agent path finding scenarios, records every run with full
provenance, and publishes the result.

**Planners not included.** They are optional extras, and an adapter whose
backend is absent reports that as a row rather than crashing.

### [→ The leaderboard](https://openplan-labs.github.io/openplan-bench/)

---

## What the numbers mean, and what they do not

A benchmark that reports only its successes is an advertisement. This one
records **every run it was asked to make**. That is the single design decision
everything else follows from:

- A run that exhausts its budget is a `timeout` row carrying the budget — never
  a missing row, and never an extrapolation of how long it "would have" taken.
  A timeout is not a proof of unsolvability.
- A planner that raises, or cannot parse a domain, is an `error` row with the
  message. "Cannot read this domain" is a real limitation and belongs in the
  table.
- A backend nobody installed is a `not-installed` row. A GPU that is not
  present is a `skipped` row. Gaps in the table are always explained.
- A returned plan is only `solved` if an **independent validator** accepts it.
  Classical plans are replayed through the grounded task; MAPF paths are
  re-scanned for vertex and edge conflicts. A plan the validator rejects shows
  as invalid and does not count towards coverage.
- An instance counts as solved for a configuration only when **every seed**
  solved it validly. A coverage number a re-run would not reproduce is not
  worth printing.

And what this is **not**:

- **Not a planner competition.** The problem set is whatever
  [pddl-examples](https://github.com/openplan-labs/pddl-examples) contains plus
  generated MAPF grids. Coverage here does not transfer to IPC coverage.
- **Not a comparison against the state of the art.** Nothing here is measured
  against Fast Downward, LAMA or EECBS. These are pure-Python research
  implementations and the numbers should be read as such.
- **Not a hardware comparison** for anything labelled `runner-grade`. Those
  suites ran on a shared GitHub Actions runner, where absolute wall times vary
  by a factor of two between runs. Their coverage, costs and node counts are
  exact; their seconds are not.

The [methodology page](https://openplan-labs.github.io/openplan-bench/methodology.html)
is the long version, and is worth reading before quoting a number.

## Install and run

```bash
git clone https://github.com/openplan-labs/openplan-bench
cd openplan-bench

python -m venv .venv && source .venv/bin/activate
pip install -e '.[all,dev]'          # or just [pddl], or just [mapf]

# The classical suites read instances from the corpus repository.
git clone https://github.com/openplan-labs/pddl-examples corpus/pddl-examples

python -m openplan_bench run suites/classical-smoke.yaml --out results/
python -m openplan_bench report results/
python -m openplan_bench site --results results/ --out docs/
```

`openplan-bench adapters` tells you which backends this machine can actually
run, and why not for the others:

```
adapter      family       status
------------------------------------------------------------
cuplan       mapf         cuplan is not importable (ModuleNotFoundError: ...). Install with: ...
fake         synthetic    ready
jupyddl      classical    ready
pymapf       mapf         ready

CUDA: unavailable — no working CUDA device (cuplan.cuda_available() returned False)
```

Other useful commands: `run --dry-run` lists the runs a suite asks for without
executing any; `run --limit N` runs only the first N per group; `env` prints
the provenance block that gets stamped onto every row.

## Suites

A suite is a declarative YAML file: what to run, on what, how many times, and
for how long. Keeping the experiment in one reviewable file is what makes
"re-run their numbers" a single command. Unknown keys are rejected, because a
typo that silently does nothing is how you publish a table measuring something
other than what its caption says.

| Suite | Family | What it is for |
| :--- | :--- | :--- |
| `classical-smoke` | PDDL | Everything finishes in milliseconds. Run it after touching the harness. |
| `classical-coverage` | PDDL | Has a real difficulty gradient — the optimal planners do not finish it. |
| `mapf-scaling` | MAPF | Runtime against agent count, 4 to 32, five seeds. |
| `mapf-density` | MAPF | Fixed agents, obstacle density 5% to 30% — where CBS actually breaks. |
| `ci-weekly` | both | Runner-grade. Time-boxed for a shared runner; watches for regressions. |

```yaml
name: classical-smoke
seeds: [0]
repetitions: 3          # classical planning is deterministic; the seed does nothing
timeout_s: 30           # hard wall-clock budget, enforced by killing the child
memory_limit_mb: 3072   # hard RLIMIT_AS, enforced inside the child

groups:
  - adapter: jupyddl
    corpus_root: ../corpus/pddl-examples
    instances:
      - dir: blocksworld
      - dir: domains/fast-downward-all-problem-suite/miconic
        group: miconic
        problems: [s1-0.pddl, s1-1.pddl]
    planners:
      - planner: astar
        heuristic: lmcut
```

## Adding a planner

**This is the main extension point.** Adding a planner to the leaderboard is
adding one module and one line — the runner, the CSV schema, the aggregation
and the site are all adapter-agnostic and none of them change.

An adapter is a thin translation layer. It does not time anything, retry
anything, enforce a budget, or decide what to run: the harness owns all of
that, so every backend is measured identically.

**1. Write `openplan_bench/adapters/yours_adapter.py`:**

```python
from ..records import Instance, RunRecord
from .base import Adapter, RunConfig, missing


class YoursAdapter(Adapter):
    name = "yours"
    family = "classical"        # or "mapf", or a family you define
    requires = ("your_backend",)

    def available(self) -> tuple[bool, str]:
        """Return (usable, reason). Never raise — a missing backend is a row."""
        ok, reason = missing(self.requires)
        return (True, "") if ok else (False, f"{reason}. Install with: pip install ...")

    def instances(self, spec: dict) -> list[Instance]:
        """Expand the suite's instance block. `payload` is yours to define."""
        return [Instance(id=name, group="g", payload={...}) for name in spec["instances"]]

    def run(self, instance, config, *, seed=0, timeout_s=60.0) -> RunRecord:
        """Solve it, and report what happened.

        Called inside a child process that already has a wall-clock alarm and a
        memory cap, so run to completion without defending yourself. Raising is
        fine — the harness turns it into an `error` row naming your adapter.
        """
        record = self.blank(instance, config, seed=seed, timeout_s=timeout_s)
        elapsed = self.timer()
        result = your_backend.solve(instance.payload, timeout=timeout_s)
        record.wall_time_s = elapsed()

        if result.solved:
            record.outcome, record.solved = "solved", True
            record.valid = your_backend.validate(result.plan)   # never self-report
            record.cost, record.plan_length = result.cost, len(result.plan)
        else:
            record.outcome = "unsolved"
        return record
```

**2. Register it** in `openplan_bench/adapters/__init__.py`:

```python
_BUILTIN = {
    ...,
    "yours": "openplan_bench.adapters.yours_adapter:YoursAdapter",
}
```

Registration is lazy — importing the registry must never import a planner,
because the harness has to work on a machine that has none of them.

**3. Add an extra** in `pyproject.toml` so `pip install 'openplan-bench[yours]'`
works, and **4. write a suite** in `suites/` that uses it.

Two rules to hold to:

- **Leave a metric `None` if the backend does not report it.** A zero in an
  `expanded` column that actually means "not measured" is worse than a blank.
- **Never claim `solved` on the planner's own say-so.** Validate the plan.

`openplan_bench/adapters/fake.py` is the smallest complete example and the one
to read first; it is also what the test suite runs against, so the timeout,
error and memory-guard paths are covered without any planner installed.

## Results

```
results/<suite>/2026-08-21.csv      one row per measured run, never overwritten
results/<suite>/latest.json         the same rows plus the suite header
```

Rows are wide on purpose. Each carries the planner, instance, seed, outcome and
metrics **and** the CPU model, platform, Python version, package versions,
timestamp and harness git SHA that produced it. That is redundant within one
file and essential the moment two files from different machines are
concatenated.

```python
from openplan_bench.records import read_csv
rows = read_csv("results/classical-coverage/2026-08-21.csv")
print(sum(r.outcome == "timeout" for r in rows), "timeouts")
```

## How a run is measured

Every run happens in a **fresh subprocess**. That costs an interpreter startup
per row and buys three things worth more than the milliseconds: a hard timeout
that works on a planner stuck inside a C extension, a hard `RLIMIT_AS` ceiling
that turns "the machine started swapping" into one row, and no cross-run
contamination from anything a planner cached or leaked.

Runs are executed **serially**. Timing N planners on N cores measures the
memory subsystem, not the planners.

Reported statistics are the **median over seeds** with the observed
**min–max** as the band — three seeds do not support a standard deviation, and
a mean is moved by one scheduling hiccup. Timing aggregates use solved runs
only, because folding a timeout's budget into a mean makes a planner look
faster as it starts failing.

## Layout

```
openplan_bench/
├── records.py      the row type, the outcome vocabulary, CSV/JSON I/O
├── provenance.py   what machine, what versions, what commit
├── suite.py        the YAML schema, validated strictly
├── runner.py       planning and executing jobs; never-overwritten output
├── worker.py       the sandboxed child that runs exactly one measurement
├── aggregate.py    medians, bands, coverage, cactus and scaling series
├── charts.py       every matplotlib call in the project (see the note inside)
├── site.py         the static dashboard generator
├── mapfgen.py      seeded MAPF instances, shared by every MAPF adapter
└── adapters/       jupyddl · pymapf · cuplan · fake
```

`charts.py` carries a migration note: when
[`planviz`](https://github.com/openplan-labs/planviz) lands it should become a
thin shim over it. Keeping every plotting call in one module is what makes that
a delete-and-import rather than a refactor.

## Brand

Colour, type and figures follow
[openplan-labs/branding](https://github.com/openplan-labs/branding) (Frontier).
The categorical series colour is the agent ramp; `--color-path` is the only
warm colour in the system and is spent on the thing a figure is arguing. If the
tokens vendored here ever drift from that repository, that repository wins.

## Contributing

New adapters, new suites and corrections to the methodology are all welcome —
see [CONTRIBUTING.md](CONTRIBUTING.md). If you think a number here is wrong or
a caption overclaims, that is a bug report worth filing.

## Licence

MIT. See [LICENSE](LICENSE).
