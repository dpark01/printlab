"""Golden reproducibility test: two independent full pipeline runs into
different output directories must produce hash-identical normalized
artifacts. This is the Tier-1 reproducibility contract from
printlab.determinism, exercised end to end rather than at the unit level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline
from printlab.determinism import hash_artifact
from printlab.slicing import get_backend

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"
EXAMPLE_NAMES = ("bracket", "hook")

pytestmark = pytest.mark.integration

_ARTIFACT_KEYS = ("mesh", "slice_result", "gcode", "printability")


@pytest.mark.parametrize("example_name", EXAMPLE_NAMES)
def test_repeated_runs_are_hash_identical(example_name, tmp_path_factory):
    backend_name = "prusaslicer"
    if not get_backend(backend_name).detect().available:
        pytest.skip(f"{backend_name} binary not installed on this machine")

    example_dir = EXAMPLES_DIR / example_name
    output_a = tmp_path_factory.mktemp(f"{example_name}_run_a")
    output_b = tmp_path_factory.mktemp(f"{example_name}_run_b")

    result_a = pipeline.run_all(example_dir, backend_name, output_dir=output_a)
    result_b = pipeline.run_all(example_dir, backend_name, output_dir=output_b)

    for key in _ARTIFACT_KEYS:
        hash_a = hash_artifact(result_a[key])
        hash_b = hash_artifact(result_b[key])
        assert hash_a == hash_b, f"{key} artifact hash differs between independent runs"
