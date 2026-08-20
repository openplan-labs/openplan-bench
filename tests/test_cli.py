"""The command line, end to end, on the fake adapter."""

from __future__ import annotations

import textwrap

from openplan_bench.cli import main


def _suite(tmp_path):
    path = tmp_path / "cli.yaml"
    path.write_text(
        textwrap.dedent(
            """
            name: cli
            title: CLI suite
            description: A suite the CLI tests drive.
            seeds: [0, 1]
            groups:
              - adapter: fake
                instances: [{id: alpha}, {id: beta}]
                planners: [{planner: p}]
            """
        ),
        encoding="utf-8",
    )
    return path


def test_no_arguments_prints_help(capsys):
    assert main([]) == 1
    assert "openplan-bench" in capsys.readouterr().out


def test_dry_run_executes_nothing(tmp_path, capsys):
    assert main(["run", str(_suite(tmp_path)), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "4 run(s) would be executed" in out
    assert not (tmp_path / "results").exists()


def test_run_report_site_round_trip(tmp_path, capsys):
    results = tmp_path / "results"
    docs = tmp_path / "docs"

    assert main(["run", str(_suite(tmp_path)), "--out", str(results)]) == 0
    assert (results / "cli" / "latest.json").exists()
    assert list((results / "cli").glob("*.csv"))
    capsys.readouterr()

    assert main(["report", str(results)]) == 0
    report = capsys.readouterr().out
    assert "CLI suite" in report
    assert "fake:p" in report
    assert "100.0%" in report

    args = ["site", "--results", str(results), "--out", str(docs), "--no-figures"]
    assert main(args) == 0
    index = (docs / "index.html").read_text()
    assert "CLI suite" in index
    assert "alpha" in index and "beta" in index


def test_report_on_an_empty_directory_fails_loudly(tmp_path, capsys):
    assert main(["report", str(tmp_path / "nope")]) == 1
    assert "No results" in capsys.readouterr().err


def test_bad_suite_path_is_an_error_not_a_traceback(tmp_path, capsys):
    assert main(["run", str(tmp_path / "missing.yaml")]) == 2
    assert "No such suite file" in capsys.readouterr().err


def test_adapters_command_lists_every_adapter(capsys):
    assert main(["adapters"]) == 0
    out = capsys.readouterr().out
    for name in ("jupyddl", "pymapf", "cuplan", "fake"):
        assert name in out
    assert "CUDA:" in out


def test_env_command_emits_json(capsys):
    import json

    assert main(["env"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["python_version"]
    assert "openplan-bench" in payload["package_versions"]
