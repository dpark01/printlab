"""Parser tests against small, hand-verified fixture G-code files.

Expected values are computed by hand-tracing the parser's virtual-E
reconstruction algorithm (see printlab.gcode.parser docstring) against each
fixture -- these numbers are not copied from a slicer's own report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab.gcode import analyze, parse_gcode


def test_parse_prusaslicer_absolute_extrusion(fixtures_dir: Path):
    text = (fixtures_dir / "gcode" / "prusaslicer_sample.gcode").read_text()
    result = parse_gcode(text)

    assert result.layer_count == 2
    assert result.first_layer_height_mm == pytest.approx(0.2)
    assert result.layer_height_mm == pytest.approx(0.2)
    # Retract (E1.2) then prime back to the same physical position (E0.8
    # after a G92 E0 reset, offset 1.2 -> virtual 2.0) must not double count.
    assert result.filament_length_mm == pytest.approx(3.8)
    assert result.estimated_time_s == pytest.approx(65.0)


def test_parse_bambu_relative_extrusion(fixtures_dir: Path):
    text = (fixtures_dir / "gcode" / "bambu_sample.gcode").read_text()
    result = parse_gcode(text)

    assert result.layer_count == 2
    assert result.first_layer_height_mm == pytest.approx(0.2)
    assert result.layer_height_mm == pytest.approx(0.2)
    # Relative-mode retract (-0.8) then prime (+0.8) must net to zero.
    assert result.filament_length_mm == pytest.approx(3.6)
    assert result.estimated_time_s == pytest.approx(70.0)


def test_retract_prime_cycle_does_not_double_count():
    """Regression test for the bug this parser originally had: naively
    summing positive E deltas overcounts every retract/un-retract cycle."""
    text = "\n".join(
        [
            "M82",
            "G92 E0",
            "G1 X1 Y1 E5.0",  # extrude 5.0mm
            "G1 X2 Y1 E4.2",  # retract 0.8mm (not counted)
            "G92 E0",
            "G1 X3 Y1 E0.8",  # prime back to the same physical point (not new filament)
            "G1 X4 Y1 E1.8",  # extrude 1.0mm more -> total should be 6.0mm
        ]
    )
    result = parse_gcode(text)
    assert result.filament_length_mm == pytest.approx(6.0)


def test_no_layer_markers_returns_zero_layers():
    result = parse_gcode("G1 X1 Y1\nG1 X2 Y2\n")
    assert result.layer_count == 0
    assert result.first_layer_height_mm is None


def test_analyze_reports_authoritative_metrics(fixtures_dir: Path):
    gcode_path = fixtures_dir / "gcode" / "prusaslicer_sample.gcode"
    report = analyze(gcode_path, backend="prusaslicer", material_density_g_cm3=1.24)

    assert report.layer_count == 2
    assert report.filament_length_mm == pytest.approx(3.8)
    # Mass is always computed by PrintLab from material density, never
    # scraped from a slicer's own report.
    filament_radius_mm = 1.75 / 2
    expected_volume_mm3 = 3.8 * 3.141592653589793 * filament_radius_mm**2
    expected_mass_g = (expected_volume_mm3 / 1000.0) * 1.24
    assert report.filament_mass_g == pytest.approx(expected_mass_g)


def test_analyze_warns_when_no_layers_detected(tmp_path: Path):
    gcode_path = tmp_path / "empty.gcode"
    gcode_path.write_text("G1 X1 Y1\n")
    report = analyze(gcode_path, backend="prusaslicer", material_density_g_cm3=1.24)
    assert report.status.value == "warning"
    assert any(e.code == "no_layers_detected" for e in report.errors)
