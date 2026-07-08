"""Slicer-free golden reproducibility test for `printlab check`
(printlab.pipeline.run_check): two independent runs into different output
directories must produce hash-identical normalized mesh/printability
artifacts. Needs a real CadQuery build like test_pipeline_golden.py, but --
unlike that suite -- requires no slicer and is never skipped: this is the
concrete demonstration that the mesh-derived printability checks don't
depend on one (see docs/environment.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline
from printlab.determinism import hash_artifact

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"
EXAMPLE_NAMES = ("bracket", "hook")

pytestmark = pytest.mark.integration

_ARTIFACT_KEYS = ("mesh", "printability")


@pytest.mark.parametrize("example_name", EXAMPLE_NAMES)
def test_repeated_checks_are_hash_identical(example_name, tmp_path_factory):
    example_dir = EXAMPLES_DIR / example_name
    output_a = tmp_path_factory.mktemp(f"{example_name}_check_a")
    output_b = tmp_path_factory.mktemp(f"{example_name}_check_b")

    result_a = pipeline.run_check(example_dir, output_dir=output_a)
    result_b = pipeline.run_check(example_dir, output_dir=output_b)

    for key in _ARTIFACT_KEYS:
        hash_a = hash_artifact(result_a[key])
        hash_b = hash_artifact(result_b[key])
        assert hash_a == hash_b, f"{key} artifact hash differs between independent runs"


def test_check_succeeds_with_gcode_metrics_null(tmp_path):
    """The whole point of `check`: it never probes for a slicer at all."""
    result = pipeline.run_check(EXAMPLES_DIR / "bracket", output_dir=tmp_path)
    assert result["printability"].status.value != "error"
    assert result["printability"].metrics["filament_mass_g"] is None
    assert result["printability"].metrics["volume_mm3"] is not None
    assert (tmp_path / "report.md").is_file()
    assert (tmp_path / "report.html").is_file()
