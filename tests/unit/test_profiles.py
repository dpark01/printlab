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


def test_load_committed_quality_and_strength_process_profiles(repo_root: Path):
    quality = load_process_profile(repo_root / "profiles/processes/quality.yaml")
    strength = load_process_profile(repo_root / "profiles/processes/strength.yaml")
    assert quality.layer_height_mm < 0.2  # finer resolution than draft
    assert strength.wall_count > 2  # more walls than draft, for strength
    for profile in (quality, strength):
        assert "bambu" in profile.native_bundle
        assert "prusaslicer" in profile.native_bundle
        assert Path(profile.native_bundle["prusaslicer"]).is_file()
        assert Path(profile.native_bundle["bambu"]).is_file()


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


def test_wall_count_is_resolved_and_reaches_the_effective_settings_dict(repo_root: Path):
    """Regression test: wall_count was documented as part of the small
    override allowlist but never actually resolved or passed to a backend."""
    strength = load_process_profile(repo_root / "profiles/processes/strength.yaml")
    request = SliceRequest(
        input_model="part.stl", output_dir="out", printer_profile="p.yaml", material_profile="m.yaml"
    )
    resolved = resolve_process_overrides(request, strength)
    assert resolved.wall_count.value == strength.wall_count == 6
    assert resolved.wall_count.source == "process_profile"
    assert resolved.as_dict()["wall_count"] == 6

    request_with_override = SliceRequest(
        input_model="part.stl",
        output_dir="out",
        printer_profile="p.yaml",
        material_profile="m.yaml",
        wall_count=3,
    )
    resolved_override = resolve_process_overrides(request_with_override, strength)
    assert resolved_override.wall_count.value == 3
    assert resolved_override.wall_count.source == "request"
