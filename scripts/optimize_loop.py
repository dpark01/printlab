#!/usr/bin/env python3
"""C.11 agent optimization loop: repeat edit CAD -> build -> evaluate ->
compare -> until the metric stops improving (SETUP.md's originally-specified
agent loop).

This lives *outside* printlab/pipeline.py by the project's own design rule
(SETUP.md: this orchestration is not itself the source of engineering truth,
and PrintLab's engineering layer stays LLM-agnostic -- see AGENTS.md/
SETUP.md's core philosophy). `propose_edit` is the pluggable seam an LLM (or
anything else) plugs into; this module never calls one itself. The demo
proposer below (`make_constant_nudge_proposer`) exists only so `optimize()`
is runnable and testable with zero LLM -- it is not a real design-search
strategy.

Usage as a library:

    from printlab import pipeline
    from scripts.optimize_loop import optimize, make_constant_nudge_proposer

    result = optimize(
        "examples/hook",
        propose_edit=make_constant_nudge_proposer("ARM_LENGTH", step=-2.0, minimum=10.0),
        runner=pipeline.run_check,
        target_metric="max_unsupported_span_mm",
    )

Run as a script (the demo below, against examples/hook):

    uv run python scripts/optimize_loop.py
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from printlab import pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent

#: A metric value as it appears in PrintabilityReport.metrics.
MetricValue = float | int | bool | str | None


@dataclass(frozen=True)
class IterationRecord:
    iteration: int
    metric_value: MetricValue
    printability_status: str
    failure_count: int
    proposed_edit: bool


@dataclass(frozen=True)
class OptimizeResult:
    example_dir: Path
    target_metric: str
    direction: str
    history: list[IterationRecord] = field(default_factory=list)
    best_metric_value: MetricValue = None
    stop_reason: str = ""


def _is_improvement(value: MetricValue, best: MetricValue, direction: str) -> bool:
    if value is None:
        return False
    if best is None:
        return True
    if direction == "minimize":
        return value < best
    if direction == "maximize":
        return value > best
    raise ValueError(f"direction must be 'minimize' or 'maximize', got {direction!r}")


def optimize(
    example_dir: Path,
    *,
    propose_edit: Callable[[str, dict], str | None],
    runner: Callable[[Path], dict] = pipeline.run_check,
    target_metric: str = "max_unsupported_span_mm",
    direction: str = "minimize",
    max_iters: int = 10,
    patience: int = 3,
) -> OptimizeResult:
    """Repeat edit -> build -> evaluate -> compare until the stopping rule
    fires. Stops when, whichever comes first:

    (a) no ERROR-level printability check remains and `target_metric` hasn't
        improved for `patience` consecutive iterations,
    (b) `propose_edit` returns `None` (no further edit to try), or
    (c) `max_iters` is reached.

    `runner` receives only `example_dir`; bind a specific output directory
    or slicer backend with `functools.partial`/a lambda if needed. The
    example's CAD source is restored to its original content before
    returning, regardless of outcome -- a run never leaves the repo dirty.
    """
    example_dir = Path(example_dir)
    config = pipeline.load_part_config(example_dir)
    original_source = config.part_py.read_text()
    current_source = original_source

    history: list[IterationRecord] = []
    best_metric_value: MetricValue = None
    stall_count = 0
    stop_reason = f"reached max_iters ({max_iters})"

    try:
        for iteration in range(max_iters):
            result = runner(example_dir)
            printability = result["printability"]
            metric_value = printability.metrics.get(target_metric)
            no_errors = printability.failure_count == 0

            # An erroring iteration is never "the best": a broken (ERROR)
            # design isn't a valid candidate to compare against, even if its
            # raw metric value looks numerically better.
            if no_errors and _is_improvement(metric_value, best_metric_value, direction):
                best_metric_value = metric_value
                stall_count = 0
            else:
                stall_count += 1

            should_stop_on_plateau = no_errors and stall_count >= patience
            new_source = None if should_stop_on_plateau else propose_edit(current_source, result)

            history.append(
                IterationRecord(
                    iteration=iteration,
                    metric_value=metric_value,
                    printability_status=printability.status.value,
                    failure_count=printability.failure_count,
                    proposed_edit=new_source is not None,
                )
            )

            if should_stop_on_plateau:
                stop_reason = (
                    f"no ERROR-level check remains and {target_metric!r} has not "
                    f"improved for {patience} consecutive iterations"
                )
                break
            if new_source is None:
                stop_reason = "propose_edit returned None (no further edit proposed)"
                break

            config.part_py.write_text(new_source)
            current_source = new_source
    finally:
        config.part_py.write_text(original_source)

    return OptimizeResult(
        example_dir=example_dir,
        target_metric=target_metric,
        direction=direction,
        history=history,
        best_metric_value=best_metric_value,
        stop_reason=stop_reason,
    )


def make_constant_nudge_proposer(
    constant_name: str,
    step: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Callable[[str, dict], str | None]:
    """A deterministic demo proposer: increments `constant_name`'s numeric
    value in CAD source by `step` each call, clamped to [minimum, maximum]
    (returning `None` -- "no further edit" -- once a step would cross a
    bound). Not a real design-search strategy; a real agent supplies its own
    `propose_edit` callback instead (see module docstring).
    """
    pattern = re.compile(rf"(?m)^{re.escape(constant_name)}\s*=\s*(-?\d+(?:\.\d+)?)")

    def propose(source: str, _last_result: dict) -> str | None:
        match = pattern.search(source)
        if match is None:
            return None
        new_value = float(match.group(1)) + step
        if minimum is not None and new_value < minimum:
            return None
        if maximum is not None and new_value > maximum:
            return None
        start, end = match.span(1)
        return source[:start] + f"{new_value:g}" + source[end:]

    return propose


def _print_history(result: OptimizeResult) -> None:
    print(f"target: {result.target_metric} ({result.direction})")
    for record in result.history:
        print(
            f"  iter {record.iteration}: {result.target_metric}={record.metric_value} "
            f"status={record.printability_status} failures={record.failure_count} "
            f"proposed_edit={record.proposed_edit}"
        )
    print(f"stopped: {result.stop_reason}")
    print(f"best {result.target_metric}: {result.best_metric_value}")


def main() -> None:
    """Demo: shrink examples/hook's cantilever arm until either the search
    bottoms out (ARM_LENGTH hits its floor) or the span stops improving."""
    result = optimize(
        REPO_ROOT / "examples" / "hook",
        propose_edit=make_constant_nudge_proposer("ARM_LENGTH", step=-2.0, minimum=10.0),
        target_metric="max_unsupported_span_mm",
    )
    _print_history(result)


if __name__ == "__main__":
    main()
