"""Printability checks tested against synthetic mesh/gcode reports."""

from __future__ import annotations

from printlab.evaluation import evaluate
from printlab.schemas import BBox, GCodeReport, MeshReport, PrinterProfile, Status


def _printer(**overrides) -> PrinterProfile:
    defaults = dict(
        name="Test Printer",
        manufacturer="Test",
        build_volume_mm=(200.0, 200.0, 200.0),
        nozzle_diameter_mm=0.4,
        allowed_layer_heights_mm=[0.1, 0.2, 0.3],
        min_feature_size_mm=0.4,
    )
    defaults.update(overrides)
    return PrinterProfile(**defaults)


def _mesh(**overrides) -> MeshReport:
    defaults = dict(
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
    defaults.update(overrides)
    return MeshReport(**defaults)


def _gcode(**overrides) -> GCodeReport:
    defaults = dict(
        source_backend="test",
        gcode_sha256="abc",
        layer_count=10,
        layer_height_mm=0.2,
        first_layer_height_mm=0.2,
        filament_length_mm=100.0,
        filament_volume_mm3=200.0,
        filament_mass_g=2.0,
        material_density_g_cm3=1.24,
        estimated_time_s=60.0,
    )
    defaults.update(overrides)
    return GCodeReport(**defaults)


def test_all_checks_pass_for_healthy_part():
    report = evaluate(_mesh(), _gcode(), _printer())
    assert report.status is Status.OK
    assert report.failure_count == 0
    assert report.warning_count == 0


def test_non_manifold_mesh_is_an_error():
    mesh = _mesh(manifold=False, watertight=False)
    report = evaluate(mesh, _gcode(), _printer())
    assert report.status is Status.ERROR
    check = next(c for c in report.checks if c.name == "manifold_watertight")
    assert check.status is Status.ERROR


def test_part_exceeding_build_volume_is_an_error():
    mesh = _mesh(bbox=BBox(min=(0, 0, 0), max=(300, 10, 10)))
    report = evaluate(mesh, _gcode(), _printer())
    assert report.status is Status.ERROR
    check = next(c for c in report.checks if c.name == "build_volume_fit")
    assert check.status is Status.ERROR


def test_unusual_layer_height_is_a_warning():
    gcode = _gcode(layer_height_mm=0.37)
    report = evaluate(_mesh(), gcode, _printer())
    assert report.status is Status.WARNING
    check = next(c for c in report.checks if c.name == "layer_height_allowed")
    assert check.status is Status.WARNING


def test_overlapping_shells_is_a_warning_not_a_failure():
    mesh = _mesh(self_intersecting=True, self_intersection_count=1)
    report = evaluate(mesh, _gcode(), _printer())
    assert report.status is Status.WARNING
    check = next(c for c in report.checks if c.name == "self_intersection_heuristic")
    assert check.status is Status.WARNING


def test_metrics_are_populated():
    report = evaluate(_mesh(), _gcode(), _printer())
    assert report.metrics["volume_mm3"] == 1000.0
    assert report.metrics["layer_count"] == 10
