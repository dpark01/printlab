"""Integration tests: build the real bracket example and slice it with each
available backend. Skipped per-backend if that backend's binary isn't
installed (see printlab.slicing.detect_all). Requires CadQuery to build the
part, so this file only runs in the CI heavy lane, never the fast lane.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline
from printlab.slicing import available_backend_names, get_backend

EXAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "bracket"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def built_bracket(tmp_path_factory):
    config = pipeline.load_part_config(EXAMPLE_DIR)
    output_dir = tmp_path_factory.mktemp("bracket_build")
    _step_path, stl_path = pipeline.stage_build(config, output_dir)
    return config, stl_path


@pytest.mark.parametrize("backend_name", available_backend_names())
def test_backend_slices_the_bracket(backend_name, built_bracket, tmp_path_factory):
    backend = get_backend(backend_name)
    if not backend.detect().available:
        pytest.skip(f"{backend_name} binary not installed on this machine")

    config, stl_path = built_bracket
    printer, material, process = pipeline.load_profiles(config)
    output_dir = tmp_path_factory.mktemp(f"slice_{backend_name}")

    result = pipeline.stage_slice(
        config, stl_path, output_dir, backend_name, printer=printer, material=material, process=process
    )
    assert result.status.value == "ok", result.errors
    assert result.gcode_path is not None
    assert result.gcode_path.is_file()

    gcode_report = pipeline.stage_gcode(result, output_dir, material=material)
    assert gcode_report.layer_count > 0
    assert gcode_report.filament_mass_g > 0
    assert gcode_report.estimated_time_s > 0
