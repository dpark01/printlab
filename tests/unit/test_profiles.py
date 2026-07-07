"""Profile loading + override resolution, using the committed profiles/ YAML
(the same files the real pipeline uses)."""

from __future__ import annotations

from pathlib import Path

from printlab.profiles import (
    load_material_profile,
    load_printer_profile,
    load_process_profile,
    resolve_process_overrides,
)
from printlab.schemas import SliceRequest


def test_load_committed_printer_profile(repo_root: Path):
    profile = load_printer_profile(repo_root / "profiles/printers/bambu_a1.yaml")
    assert profile.name == "Bambu Lab A1"
    assert profile.nozzle_diameter_mm == 0.4
    assert "bambu" in profile.native_bundle
    assert "prusaslicer" in profile.native_bundle


def test_load_committed_material_profile(repo_root: Path):
    profile = load_material_profile(repo_root / "profiles/materials/pla.yaml")
    assert profile.material == "PLA"
    assert profile.density_g_cm3 > 0


def test_load_committed_process_profile(repo_root: Path):
    profile = load_process_profile(repo_root / "profiles/processes/draft.yaml")
    assert profile.layer_height_mm == 0.2


def test_resolve_process_overrides_prefers_request_value(repo_root: Path):
    process = load_process_profile(repo_root / "profiles/processes/draft.yaml")
    request = SliceRequest(
        input_model="part.stl",
        output_dir="out",
        printer_profile="p.yaml",
        material_profile="m.yaml",
        layer_height_mm=0.28,
    )
    resolved = resolve_process_overrides(request, process)
    assert resolved.layer_height_mm.value == 0.28
    assert resolved.layer_height_mm.source == "request"
    assert resolved.infill_percent.source == "process_profile"


def test_resolve_process_overrides_falls_back_to_process_profile(repo_root: Path):
    process = load_process_profile(repo_root / "profiles/processes/draft.yaml")
    request = SliceRequest(
        input_model="part.stl", output_dir="out", printer_profile="p.yaml", material_profile="m.yaml"
    )
    resolved = resolve_process_overrides(request, process)
    assert resolved.layer_height_mm.value == process.layer_height_mm
    assert resolved.layer_height_mm.source == "process_profile"
