"""Real OpenSCAD -> FreeCAD -> OCP build integration coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline
from printlab.cad.openscad import detect_openscad_toolchain
from printlab.schemas import CadBuildReport

EXAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "openscad-plate"

pytestmark = pytest.mark.integration


def test_openscad_example_builds_one_valid_brep_solid(tmp_path):
    detected = detect_openscad_toolchain()
    missing = [name for name, capability in detected.items() if not capability["available"]]
    if missing:
        pytest.skip(f"OpenSCAD CAD toolchain not installed: {', '.join(missing)}")

    config = pipeline.load_part_config(EXAMPLE_DIR)
    pipeline.prepare_output_dir(tmp_path, clean=True)

    step_path, stl_path = pipeline.stage_build(config, tmp_path)

    report = CadBuildReport.model_validate_json(
        (tmp_path / pipeline.ARTIFACT_FILENAMES["cad_build_report"]).read_text()
    )
    comparison = report.metadata["geometry_comparison"]
    assert step_path.is_file() and step_path.stat().st_size > 0
    assert stl_path.is_file() and stl_path.stat().st_size > 0
    assert report.backend_name == "openscad"
    assert set(report.tool_versions) == {"openscad", "freecad"}
    assert report.metadata["bridge"]["solid_count"] == 1
    assert report.metadata["bridge"]["fallback_objects"] == []
    assert comparison["reference_watertight"] is True
    assert comparison["candidate_watertight"] is True
    assert comparison["max_surface_deviation_mm"] <= report.settings["max_surface_deviation_mm"]
    assert comparison["relative_volume_delta"] <= report.settings["max_relative_volume_delta"]
    assert comparison["max_bbox_delta_mm"] <= report.settings["max_bbox_delta_mm"]
