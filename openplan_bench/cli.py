"""``openplan-bench`` — run suites, report on results, build the dashboard.

    openplan-bench run suites/classical-smoke.yaml --out results/
    openplan-bench report results/
    openplan-bench site --results results/ --out docs/
    openplan-bench adapters
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import aggregate, provenance
from .records import RunRecord


def _add_run(sub) -> None:
    p = sub.add_parser("run", help="run a suite and write a results file")
    p.add_argument("suite", help="path to a suite YAML file")
    p.add_argument("-o", "--out", default="results", help="results directory")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="run only the first N jobs per group (a smoke check of the suite itself)",
    )
    p.add_argument(
        "--python",
        default=None,
        help="interpreter for the worker processes (defaults to this one)",
    )
    p.add_argument("--quiet", action="store_true", help="only print the summary")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list the runs the suite asks for without executing any",
    )
    p.set_defaults(func=_cmd_run)


def _add_report(sub) -> None:
    p = sub.add_parser("report", help="summarise committed results in the terminal")
    p.add_argument("results", nargs="?", default="results", help="results directory")
    p.add_argument("--suite", default=None, help="only this suite")
    p.set_defaults(func=_cmd_report)


def _add_site(sub) -> None:
    p = sub.add_parser("site", help="generate the dashboard into docs/")
    p.add_argument("--results", default="results", help="results directory")
    p.add_argument("-o", "--out", default="docs", help="output directory")
    p.add_argument(
        "--no-figures",
        action="store_true",
        help="skip chart rendering (HTML only, much faster)",
    )
    p.set_defaults(func=_cmd_site)


def _add_adapters(sub) -> None:
    p = sub.add_parser("adapters", help="list adapters and whether they can run here")
    p.set_defaults(func=_cmd_adapters)


def _add_env(sub) -> None:
    p = sub.add_parser("env", help="print the provenance block for this machine")
    p.set_defaults(func=_cmd_env)


# ---------------------------------------------------------------------------
def _line(record: RunRecord) -> str:
    marks = {
        "solved": "ok",
        "unsolved": "--",
        "timeout": "TO",
        "memory": "MEM",
        "error": "ERR",
        "skipped": "skip",
        "not-installed": "n/a",
    }
    mark = marks.get(record.outcome, "?")
    detail = ""
    if record.outcome == "solved":
        detail = f"{record.wall_time_s:8.3f}s"
        if record.cost is not None:
            detail += f"  cost {record.cost:g}"
        if record.expanded is not None:
            detail += f"  exp {record.expanded}"
        if not record.valid:
            detail += "  INVALID PLAN"
    elif record.outcome == "timeout":
        detail = f"budget {record.timeout_s:g}s"
    elif record.note:
        detail = record.note[:70]
    return (
        f"  [{mark:>4}] {record.adapter}:{record.label} "
        f"{record.instance} seed={record.seed}  {detail}"
    )


def _cmd_run(args) -> int:
    from .runner import plan_group, run_suite, save
    from .suite import SuiteError, load_suite

    try:
        suite = load_suite(args.suite)
    except SuiteError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(f"suite: {suite.name} — {suite.title}")
    print(f"machine: {provenance.describe()}")
    print(
        f"seeds={suite.seeds} repetitions={suite.repetitions} "
        f"timeout={suite.timeout_s:g}s memory={suite.memory_limit_mb} MiB"
    )

    if args.dry_run:
        from .adapters import get_adapter

        total = 0
        for group in suite.groups:
            adapter = get_adapter(group.adapter)
            jobs = plan_group(suite, group, adapter)
            usable, reason = adapter.available()
            print(
                f"  {adapter.name}: {len(jobs)} run(s)"
                + ("" if usable else f"  [would record not-installed: {reason}]")
            )
            for job in jobs[: args.limit or 8]:
                print(f"    {job.describe()}")
            if len(jobs) > (args.limit or 8):
                print(f"    ... and {len(jobs) - (args.limit or 8)} more")
            total += len(jobs)
        print(f"\n{total} run(s) would be executed.")
        return 0

    rows = run_suite(
        suite,
        on_record=None if args.quiet else (lambda r: print(_line(r), flush=True)),
        on_message=lambda m: print(m, flush=True),
        python=args.python,
        limit=args.limit,
    )

    if not rows:
        print("No run was executed. Check the suite's groups.", file=sys.stderr)
        return 1

    csv_path, json_path = save(rows, suite, args.out)
    print("\nOutcomes:")
    for line in aggregate_summary_lines(rows):
        print(line)
    print(f"\nWrote {csv_path}")
    print(f"Wrote {json_path}")

    invalid = [r for r in rows if r.outcome == "solved" and not r.valid]
    if invalid:
        print(
            f"\nWARNING: {len(invalid)} run(s) returned a plan the validator "
            "rejected. They are recorded and do not count as solved.",
            file=sys.stderr,
        )
    return 0


def aggregate_summary_lines(rows: list[RunRecord]) -> list[str]:
    counts = aggregate.outcome_counts(rows)
    return [f"  {name:>14}: {count}" for name, count in counts.items()]


def _cmd_report(args) -> int:
    from .site import load_results

    results = load_results(args.results)
    if args.suite:
        results = [r for r in results if r.name == args.suite]
    if not results:
        print(f"No results under {args.results}", file=sys.stderr)
        return 1

    for result in results:
        print(f"\n=== {result.name} — {result.title} ===")
        print(f"{result.machine}")
        if result.runner_grade:
            print("RUNNER-GRADE: times are not a hardware comparison.")
        print()
        summaries = aggregate.summarize(result.rows)
        header = (
            f"{'configuration':<34} {'family':<10} {'cov':>7} "
            f"{'solved':>7} {'inst':>5} {'TO':>4} {'ERR':>4} {'median':>10}"
        )
        print(header)
        print("-" * len(header))
        for summary in summaries:
            if not summary.was_run:
                print(
                    f"{summary.adapter + ':' + summary.label:<34} "
                    f"{summary.family:<10} "
                    f"{'not run':>7} "
                    f"{'—':>7} {'—':>5} {'—':>4} {'—':>4} "
                    f"({summary.not_run} run(s) never attempted)"
                )
                continue
            print(
                f"{summary.adapter + ':' + summary.label:<34} "
                f"{summary.family:<10} "
                f"{100 * summary.coverage:6.1f}% "
                f"{summary.solved:>7} {summary.instances:>5} "
                f"{summary.timeouts:>4} {summary.errors:>4} "
                f"{(summary.median_time or 0):>9.4f}s"
            )
        print()
        for line in aggregate_summary_lines(result.rows):
            print(line)
    return 0


def _cmd_site(args) -> int:
    from .site import build

    written = build(args.results, args.out, render_figures=not args.no_figures)
    print(f"Wrote {len(written)} file(s) into {args.out}/")
    index = Path(args.out) / "index.html"
    print(f"Open {index.resolve()}")
    return 0


def _cmd_adapters(args) -> int:
    from .adapters import available_adapters, get_adapter

    print(f"{'adapter':<12} {'family':<12} status")
    print("-" * 60)
    for name in available_adapters():
        adapter = get_adapter(name)
        usable, reason = adapter.available()
        status = "ready" if usable else reason
        print(f"{name:<12} {adapter.family:<12} {status}")

    from .adapters.cuplan_adapter import cuda_usable

    ok, reason = cuda_usable()
    print(f"\nCUDA: {'available' if ok else 'unavailable — ' + reason}")
    return 0


def _cmd_env(args) -> int:
    import json

    print(json.dumps(provenance.collect(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openplan-bench",
        description=(
            "Reproducible benchmarks for the OpenPlan Labs planners. "
            "Every requested run produces a row, including the ones that "
            "time out, error, or could not be attempted."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    _add_run(sub)
    _add_report(sub)
    _add_site(sub)
    _add_adapters(sub)
    _add_env(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
