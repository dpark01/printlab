"""Markdown report rendering tests."""

from __future__ import annotations

from printlab.reporting import render_markdown
from printlab.schemas import (
    BBox,
    GCodeReport,
    MeshReport,
    PrintabilityCheck,
    PrintabilityReport,
    RunManifest,
    SliceResult,
    Status,
)


def _sample_artifacts():
    mesh = MeshReport(
        input_path="part.stl",
        input_sha256="abc",
        manifold=True,
        watertight=True,
        self_intersecting=False,
        self_intersection_count=0,
        shell_count=1,
        bbox=BBox(min=(0, 0, 0), max=(10, 10, 10)),
        surface_area_mm2=600.0,
        volume_mm3=1000.0,
    )
    slice_result = SliceResult(backend="prusaslicer", backend_version="2.9.6", gcode_path="part.gcode")
    gcode = GCodeReport(
        source_backend="prusaslicer",
        gcode_sha256="abc",
        layer_count=10,
        layer_height_mm=0.2,
        first_layer_height_mm=0.2,
        filament_length_mm=100.0,
        filament_volume_mm3=200.0,
        filament_mass_g=2.0,
        material_density_g_cm3=1.24,
        estimated_time_s=120.0,
    )
    printability = PrintabilityReport(
        metrics={"volume_mm3": 1000.0},
        checks=[PrintabilityCheck(name="manifold_watertight", status=Status.OK, message="ok")],
    )
    manifest = RunManifest(printlab_version="0.1.0", platform="test", created_at="2024-01-01T00:00:00Z")
    return mesh, slice_result, gcode, printability, manifest


def test_render_markdown_includes_key_sections():
    mesh, slice_result, gcode, printability, manifest = _sample_artifacts()
    text = render_markdown(
        part_name="bracket",
        mesh=mesh,
        slice_result=slice_result,
        gcode=gcode,
        printability=printability,
        manifest=manifest,
    )
    assert "bracket" in text
    assert "prusaslicer 2.9.6" in text
    assert "PASS" in text
    assert "manifold_watertight" in text
    assert "0.1.0" in text
