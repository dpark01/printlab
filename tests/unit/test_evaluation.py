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
        min_wall_thickness_mm=2.0,
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


def test_wall_thinner_than_min_feature_size_is_a_warning():
    mesh = _mesh(min_wall_thickness_mm=0.1)  # printer min_feature_size_mm is 0.4
    report = evaluate(mesh, _gcode(), _printer())
    assert report.status is Status.WARNING
    check = next(c for c in report.checks if c.name == "min_wall_thickness")
    assert check.status is Status.WARNING


def test_unknown_wall_thickness_is_a_warning_not_a_pass():
    mesh = _mesh(min_wall_thickness_mm=None)
    report = evaluate(mesh, _gcode(), _printer())
    check = next(c for c in report.checks if c.name == "min_wall_thickness")
    assert check.status is Status.WARNING


def test_unusual_layer_height_is_a_warning():
    gcode = _gcode(layer_height_mm=0.37)
    report = evaluate(_mesh(), gcode, _printer())
    assert report.status is Status.WARNING
    check = next(c for c in report.checks if c.name == "layer_height_allowed")
    assert check.status is Status.WARNING


def test_layer_height_within_floating_point_noise_still_passes():
    """Regression test: real slicer G-code has been observed reporting
    e.g. 0.200001mm for a nominal 0.2mm layer height (see
    printlab.gcode.parser). That must still pass this check."""
    gcode = _gcode(layer_height_mm=0.200001)
    report = evaluate(_mesh(), gcode, _printer())
    check = next(c for c in report.checks if c.name == "layer_height_allowed")
    assert check.status is Status.OK


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


def test_no_gcode_still_runs_mesh_derived_checks():
    """printlab check (pipeline.run_check) passes gcode=None when slicing was
    skipped entirely -- mesh-derived checks must still produce a real verdict."""
    mesh = _mesh(min_wall_thickness_mm=0.1)  # printer min_feature_size_mm is 0.4
    report = evaluate(mesh, None, _printer())
    assert report.status is Status.WARNING
    manifold_check = next(c for c in report.checks if c.name == "manifold_watertight")
    assert manifold_check.status is Status.OK
    wall_check = next(c for c in report.checks if c.name == "min_wall_thickness")
    assert wall_check.status is Status.WARNING


def test_no_gcode_degrades_layer_height_check_to_warning_not_error():
    report = evaluate(_mesh(), None, _printer())
    check = next(c for c in report.checks if c.name == "layer_height_allowed")
    assert check.status is Status.WARNING


def test_no_gcode_nulls_gcode_derived_metrics():
    report = evaluate(_mesh(), None, _printer())
    assert report.metrics["volume_mm3"] == 1000.0
    assert report.metrics["layer_count"] is None
    assert report.metrics["filament_length_mm"] is None
    assert report.metrics["filament_mass_g"] is None
    assert report.metrics["estimated_time_s"] is None


def test_no_gcode_non_manifold_mesh_is_still_an_error():
    mesh = _mesh(manifold=False, watertight=False)
    report = evaluate(mesh, None, _printer())
    assert report.status is Status.ERROR


def test_healthy_part_scores_100_and_is_uncalibrated():
    report = evaluate(_mesh(), _gcode(), _printer())
    assert report.provisional_score == 100
    assert report.score_calibrated is False


def test_provisional_score_decreases_as_more_checks_fail():
    healthy = evaluate(_mesh(), _gcode(), _printer())
    non_manifold = evaluate(_mesh(manifold=False, watertight=False), _gcode(), _printer())
    # non-manifold (ERROR) plus an oversized bbox (a second ERROR)
    two_errors = evaluate(
        _mesh(manifold=False, watertight=False, bbox=BBox(min=(0, 0, 0), max=(300, 10, 10))),
        _gcode(),
        _printer(),
    )
    assert healthy.provisional_score == 100
    assert non_manifold.provisional_score == 60
    assert two_errors.provisional_score == 20
    assert healthy.provisional_score > non_manifold.provisional_score > two_errors.provisional_score


def test_provisional_score_floored_at_zero_for_worst_case():
    # both ERROR-capable checks fail plus all three WARNING-capable checks:
    # 100 - 2*40 - 3*10 = -10, floored to 0.
    mesh = _mesh(
        manifold=False,
        watertight=False,
        bbox=BBox(min=(0, 0, 0), max=(300, 10, 10)),
        self_intersecting=True,
        self_intersection_count=1,
        min_wall_thickness_mm=0.1,
    )
    gcode = _gcode(layer_height_mm=0.37)
    report = evaluate(mesh, gcode, _printer())
    assert report.provisional_score == 0


def test_single_warning_costs_less_than_single_error():
    one_warning = evaluate(_mesh(min_wall_thickness_mm=0.1), _gcode(), _printer())
    one_error = evaluate(_mesh(manifold=False, watertight=False), _gcode(), _printer())
    assert one_warning.provisional_score > one_error.provisional_score


def test_no_gcode_check_path_scores_90():
    """Pins the documented check-vs-all behavior: with gcode=None the
    layer_height_allowed check degrades to WARNING, so an otherwise healthy
    part scores 90 via `check` vs. 100 via `all`."""
    report = evaluate(_mesh(), None, _printer())
    assert report.provisional_score == 90


def test_score_calibrated_is_always_false():
    for report in (
        evaluate(_mesh(), _gcode(), _printer()),
        evaluate(_mesh(manifold=False, watertight=False), _gcode(), _printer()),
        evaluate(_mesh(min_wall_thickness_mm=0.1), None, _printer()),
    ):
        assert report.score_calibrated is False
