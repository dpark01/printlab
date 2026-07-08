"""C.11 acceptance test: optimize() actually shrinks examples/hook's
cantilever across real pipeline runs -- needs a real CadQuery build, but no
slicer (uses pipeline.run_check, like test_check_golden.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline
from scripts.optimize_loop import make_constant_nudge_proposer, optimize

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"

pytestmark = pytest.mark.integration


def test_optimize_shrinks_the_hook_cantilever_and_restores_source():
    hook_dir = EXAMPLES_DIR / "hook"
    original_source = (hook_dir / "part.py").read_text()

    result = optimize(
        hook_dir,
        propose_edit=make_constant_nudge_proposer("ARM_LENGTH", step=-4.0, minimum=16.0),
        runner=pipeline.run_check,
        target_metric="max_unsupported_span_mm",
        max_iters=8,
        patience=3,
    )

    assert (hook_dir / "part.py").read_text() == original_source
    assert len(result.history) >= 2
    assert all(record.failure_count == 0 for record in result.history)
    first_span = result.history[0].metric_value
    assert result.best_metric_value < first_span
