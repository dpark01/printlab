"""Real OpenSCAD -> FreeCAD -> OCP build integration coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline
from printlab.cad import CadBuildError, CadBuildRequest
from printlab.cad.openscad import OpenSCADBackend, detect_openscad_toolchain
from printlab.schemas import CadBuildReport

EXAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "openscad-plate"

pytestmark = pytest.mark.integration


def _require_openscad_toolchain() -> None:
    detected = detect_openscad_toolchain()
    missing = [name for name, capability in detected.items() if not capability["available"]]
    if missing:
        pytest.skip(f"OpenSCAD CAD toolchain not installed: {', '.join(missing)}")


def _build_source(tmp_path: Path, source: str):
    _require_openscad_toolchain()
    source_path = tmp_path / "part.scad"
    source_path.write_text(source)
    return OpenSCADBackend().build(
        CadBuildRequest(source_path=source_path, output_dir=tmp_path / "output")
    )


def test_openscad_example_builds_one_valid_brep_solid(tmp_path):
    _require_openscad_toolchain()
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


def test_bridge_recomputes_extrusion_before_intersection(tmp_path):
    result = _build_source(
        tmp_path,
        """intersection() {
    linear_extrude(height=10) square([20, 20]);
    cube([10, 10, 10]);
}
""",
    )

    assert result.metadata["bridge"]["solid_count"] == 1
    assert result.metadata["bridge"]["volume_mm3"] == pytest.approx(1000.0)


def test_bridge_handles_extruded_2d_union_fragments(tmp_path):
    result = _build_source(
        tmp_path,
        """linear_extrude(height=10)
union() {
    square([20, 20]);
    translate([10, 10]) square([20, 20]);
}
""",
    )

    assert result.metadata["bridge"]["imported_solid_count"] >= 1
    assert result.metadata["bridge"]["solid_count"] == 1
    assert result.metadata["bridge"]["volume_mm3"] == pytest.approx(7000.0)


def test_bridge_rejects_disconnected_solids_with_actionable_metadata(tmp_path):
    with pytest.raises(CadBuildError) as exc_info:
        _build_source(
            tmp_path,
            """union() {
    cube([10, 10, 10]);
    translate([20, 0, 0]) cube([10, 10, 10]);
}
""",
        )

    assert exc_info.value.code == "freecad_multiple_solids"
    assert exc_info.value.context["solid_count"] == 2
    assert "one connected volume" in exc_info.value.context["hint"]
