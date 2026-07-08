"""B.9 acceptance test: examples/hook was deliberately designed with a bad
default-orientation cantilever (SETUP.md's ~32mm case) -- orientation search
must recommend rotating away from it. Needs a real CadQuery build, but --
like test_check_golden.py -- no slicer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"

pytestmark = pytest.mark.integration


def test_orientation_search_recommends_rotating_the_hook_arm_up(tmp_path):
    check_result = pipeline.run_check(EXAMPLES_DIR / "hook", output_dir=tmp_path)
    default_span = check_result["mesh"].max_unsupported_span_mm
    assert default_span is not None and default_span > 20.0  # SETUP.md's ~32mm cantilever

    report = pipeline.stage_orientation_search(check_result["stl_path"], tmp_path)

    winner = report.candidates[report.selected_index]
    assert winner.label != "identity"
    assert (winner.max_unsupported_span_mm or 0.0) < default_span
