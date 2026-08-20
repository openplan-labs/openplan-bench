# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Note that **results files are append-only** and are not versioned along with
the code. A schema change to `RunRecord` bumps `SCHEMA_VERSION` in
`openplan_bench/records.py`; readers tolerate unknown columns, so old results
files stay readable.

## [Unreleased]

## [0.1.0] — 2026-08-21

First release. The harness, five suites, the dashboard, and a real first run.

### Added

- **The results schema.** `RunRecord` — one wide, self-describing row per
  measured run, carrying the measurement and the conditions it was taken under:
  CPU model, platform, Python version, package versions, timestamp, seed and
  the harness git SHA. A closed outcome vocabulary (`solved`, `unsolved`,
  `timeout`, `memory`, `error`, `skipped`, `not-installed`) with no way to
  express "this run happened but is not in the file".
- **The adapter interface.** `available()` / `instances()` / `run()`, one
  module per backend under `openplan_bench/adapters/`. Adding a planner is one
  module and one registry line; nothing else in the harness changes.
  Registration is lazy, so importing the registry never imports a planner.
- **Adapters** for `jupyddl` (classical PDDL), `pymapf` (MAPF), `cuplan`
  (MAPF, CPU and CUDA) and `fake` (deterministic, for the tests).
- **Optional-by-design backends.** `[pddl]`, `[mapf]` and `[cuda]` extras; the
  harness installs, tests and builds the site with none of them present, and a
  missing backend produces `not-installed` rows rather than an exception.
- **CUDA auto-skip.** The CUDA arm is gated on `cuplan.cuda_available()`, which
  runs a real kernel and checks the answer rather than merely importing CuPy. A
  machine with no working device records `skipped` rows carrying the reason —
  never a failure, and never a CPU run relabelled as CUDA. `CUPLAN_FORCE_CPU`
  is honoured.
- **A sandboxed worker.** Every run executes in a fresh subprocess with a hard
  wall-clock kill and an `RLIMIT_AS` ceiling, so a planner stuck inside a C
  extension costs one row rather than the sweep. Runs are serial by design.
- **Shared MAPF instance generation** (`mapfgen.py`), owned by the harness, so
  `pymapf` and `cuplan` are handed byte-identical grids, starts and goals and
  their sum-of-costs columns are a comparison rather than a coincidence.
- **Declarative suites** in `suites/`, validated strictly — unknown top-level
  keys are rejected. `classical-smoke`, `classical-coverage`, `mapf-scaling`,
  `mapf-density` and the runner-grade `ci-weekly`.
- **Aggregation** with medians over seeds and min–max bands, coverage counted
  only where every seed produced a valid solution, and timing statistics taken
  from solved runs alone.
- **The dashboard** (`site.py`): a Frontier-branded static site with sortable
  and filterable tables, cactus / coverage / outcome / scaling figures rendered
  light and dark, a methodology page stating what is *not* measured, and a
  reproduce page that is honest about what will differ on another machine.
  Vanilla JavaScript, no external requests, all three viewer theme states.
- **CI**: `ci.yml` (ruff plus pytest on 3.10–3.13 with no planner installed,
  and a separate end-to-end job with the real ones), `bench.yml` (weekly
  runner-grade suite, commits results, redeploys), `docs.yml` (Pages).

### The first run

892 rows across four suites, measured on an 11th Gen Intel Core i7-11850H
(16 logical CPUs) with jupyddl 2.3.0 and pymapf 0.8.0, all from one clean
harness commit.

| Suite | Rows | Solved | Timeout | Unsolved | Error | Not run |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `classical-smoke` | 234 | 198 | 0 | 18 | 18 | 0 |
| `classical-coverage` | 108 | 68 | 28 | 6 | 6 | 0 |
| `mapf-scaling` | 400 | 228 | 17 | 5 | 0 | 150 |
| `mapf-density` | 150 | 130 | 16 | 4 | 0 | 0 |

The failures are in the tables on purpose, and several of them are the most
informative rows in the run:

- The `grid` instance raises `UnsupportedFeatureError` on every configuration:
  it is written with numeric fluents (`(wall (+ xpos 1) ypos)`) that jupyddl
  does not ground. "Cannot read this domain" is a real limitation.
- `vehicle` is `unsolved` everywhere in 6 ms. The instance ships with an
  undeclared object in its goal, so nothing can reach it.
- On `classical-coverage`, greedy best-first reaches 88.9% coverage while every
  optimal or uninformed configuration reaches 50%. The whole gap is the larger
  miconic instances, where A*/LM-Cut exhausts a 20-second budget after ~100
  expansions and greedy best-first with h_FF finishes in ~0.2 s.
- On `mapf-scaling`, CBS solves nothing above 16 agents and LaCAM solves
  everything, which is what the two algorithms' guarantees predict.
- The 150 `not-installed` rows are the `cuplan` groups: `cuda-planning` is not
  on PyPI, so it was absent. The runs were still enumerated and each says why.

### Fixed before release, by the first run itself

- pymapf's CBS consumed its full 20-second budget, returned a bare `None`, and
  was being recorded as `unsolved` — crediting it with a conclusion it never
  reached. The adapter now reads pymapf's `failed` event and records `timeout`.
  This moved 17 rows in `mapf-scaling` and 16 in `mapf-density`.
- The `cuplan` CPU and CUDA arms shared a leaderboard label, which would have
  averaged two backends into one row. Configurations now carry a `variant`.
- The scaling band was computed from per-cell medians rather than the observed
  values, which understated the spread.

[Unreleased]: https://github.com/openplan-labs/openplan-bench/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/openplan-labs/openplan-bench/releases/tag/v0.1.0
