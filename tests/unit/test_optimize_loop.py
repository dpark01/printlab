"""Unit tests for scripts/optimize_loop.py's loop logic, using a scripted
mock runner -- no CadQuery/pipeline.run_check involved, so this stays in the
fast lane."""

from __future__ import annotations

from pathlib import Path

from printlab.schemas import PrintabilityCheck, PrintabilityReport, Status
from scripts.optimize_loop import make_constant_nudge_proposer, optimize


def _make_example_dir(tmp_path: Path) -> Path:
    example_dir = tmp_path / "fake_part"
    example_dir.mkdir()
    (example_dir / "part.py").write_text("CONST = 10.0\n")
    (example_dir / "printlab.toml").write_text(
        """[part]
name = "fake"
module = "part.py"
function = "build"

[profiles]
printer = "profiles/printers/bambu_a1.yaml"
material = "profiles/materials/pla.yaml"
process = "profiles/processes/draft.yaml"
"""
    )
    return example_dir


def _report(metric_value: float | None, *, has_error: bool = False) -> PrintabilityReport:
    status = Status.ERROR if has_error else Status.OK
    checks = [PrintabilityCheck(name="dummy", status=status, message="x")]
    return PrintabilityReport(metrics={"target": metric_value}, checks=checks, status=status)


def _scripted_runner(reports: list[PrintabilityReport]):
    calls = {"count": 0}

    def runner(_example_dir: Path) -> dict:
        index = min(calls["count"], len(reports) - 1)
        calls["count"] += 1
        return {"printability": reports[index]}

    runner.calls = calls
    return runner


def _always_propose(source: str, _result: dict) -> str | None:
    return source  # a no-op edit -- exercising loop control flow, not the proposer


def test_stops_on_plateau_after_patience_iterations(tmp_path):
    example_dir = _make_example_dir(tmp_path)
    reports = [_report(10.0), _report(8.0), _report(8.0), _report(8.0), _report(8.0)]
    runner = _scripted_runner(reports)

    result = optimize(
        example_dir, propose_edit=_always_propose, runner=runner, target_metric="target", patience=2
    )

    assert result.best_metric_value == 8.0
    assert "improved" in result.stop_reason
    assert len(result.history) == 4
    assert runner.calls["count"] == 4


def test_errors_block_stopping_even_past_patience(tmp_path):
    """A plateaued metric must NOT stop the loop while an ERROR check
    remains, and an erroring iteration's metric is never recorded as "best"
    (a broken design is not a valid candidate) -- so the patience count only
    starts accumulating once error-free readings begin."""
    example_dir = _make_example_dir(tmp_path)
    reports = [
        _report(5.0, has_error=True),
        _report(5.0, has_error=True),
        _report(5.0, has_error=False),
        _report(5.0, has_error=False),
    ]
    runner = _scripted_runner(reports)

    result = optimize(
        example_dir, propose_edit=_always_propose, runner=runner, target_metric="target", patience=1
    )

    assert len(result.history) == 4
    assert result.history[-1].failure_count == 0
    assert result.best_metric_value == 5.0
    assert "improved" in result.stop_reason


def test_erroring_iteration_is_never_recorded_as_best(tmp_path):
    """A numerically-lower metric from a BROKEN (ERROR) design must not
    overwrite a prior valid best -- see the loop's no_errors guard."""
    example_dir = _make_example_dir(tmp_path)
    reports = [_report(10.0), _report(5.0, has_error=True), _report(9.0)]
    runner = _scripted_runner(reports)

    result = optimize(
        example_dir,
        propose_edit=_always_propose,
        runner=runner,
        target_metric="target",
        max_iters=3,
        patience=100,
    )

    assert result.best_metric_value == 9.0


def test_stops_immediately_when_proposer_returns_none(tmp_path):
    example_dir = _make_example_dir(tmp_path)
    reports = [_report(10.0), _report(9.0), _report(8.0)]
    runner = _scripted_runner(reports)

    result = optimize(
        example_dir,
        propose_edit=lambda _source, _result: None,
        runner=runner,
        target_metric="target",
        patience=100,
    )

    assert len(result.history) == 1
    assert result.history[0].proposed_edit is False
    assert "propose_edit returned None" in result.stop_reason


def test_stops_at_max_iters_when_metric_keeps_improving(tmp_path):
    example_dir = _make_example_dir(tmp_path)
    reports = [_report(10.0), _report(9.0), _report(8.0)]
    runner = _scripted_runner(reports)

    result = optimize(
        example_dir,
        propose_edit=_always_propose,
        runner=runner,
        target_metric="target",
        max_iters=3,
        patience=100,
    )

    assert len(result.history) == 3
    assert result.stop_reason == "reached max_iters (3)"
    assert result.best_metric_value == 8.0


def test_maximize_direction_prefers_larger_values(tmp_path):
    example_dir = _make_example_dir(tmp_path)
    reports = [_report(1.0), _report(2.0), _report(2.0)]
    runner = _scripted_runner(reports)

    result = optimize(
        example_dir,
        propose_edit=_always_propose,
        runner=runner,
        target_metric="target",
        direction="maximize",
        patience=1,
    )

    assert result.best_metric_value == 2.0


def test_cad_source_is_restored_after_the_loop(tmp_path):
    example_dir = _make_example_dir(tmp_path)
    part_py = example_dir / "part.py"
    original_text = part_py.read_text()
    reports = [_report(10.0), _report(9.0), _report(8.0)]
    runner = _scripted_runner(reports)

    optimize(
        example_dir,
        propose_edit=make_constant_nudge_proposer("CONST", step=1.0),
        runner=runner,
        target_metric="target",
        max_iters=3,
        patience=100,
    )

    assert part_py.read_text() == original_text


def test_constant_nudge_proposer_replaces_value_in_place():
    proposer = make_constant_nudge_proposer("ARM_LENGTH", step=-2.0)
    source = "ARM_LENGTH = 30.0  # comment\nother = 1\n"
    new_source = proposer(source, {})
    assert "ARM_LENGTH = 28" in new_source
    assert "# comment" in new_source


def test_constant_nudge_proposer_stops_at_minimum():
    proposer = make_constant_nudge_proposer("ARM_LENGTH", step=-2.0, minimum=29.0)
    assert proposer("ARM_LENGTH = 30.0\n", {}) is None


def test_constant_nudge_proposer_returns_none_if_constant_missing():
    proposer = make_constant_nudge_proposer("MISSING", step=1.0)
    assert proposer("OTHER = 1\n", {}) is None
