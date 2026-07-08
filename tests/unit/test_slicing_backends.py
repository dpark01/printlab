"""Backend logic tests using a mocked subprocess call -- no real slicer
binary needed, so this stays in the CI fast lane (unlike
tests/integration/test_slicing_backends.py, which exercises real binaries).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from printlab.schemas import MaterialProfile, PrinterProfile, ProcessProfile, SliceRequest, Status
from printlab.slicing.bambu import BambuStudioBackend
from printlab.slicing.orcaslicer import OrcaSlicerBackend
from printlab.slicing.prusaslicer import PrusaSlicerBackend

_JSON_BACKENDS = ("bambu", "orcaslicer")


def _fake_completed_process(returncode: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr="")


def _profiles(tmp_path: Path, backend_name: str):
    native_dir = tmp_path / "native"
    native_dir.mkdir()
    ext = "json" if backend_name in _JSON_BACKENDS else "ini"
    machine = native_dir / f"machine.{ext}"
    filament = native_dir / f"filament.{ext}"
    process = native_dir / f"process.{ext}"
    if backend_name in _JSON_BACKENDS:
        for path in (machine, filament, process):
            path.write_text("{}")
    else:
        for path in (machine, filament, process):
            path.write_text("")

    printer = PrinterProfile(
        name="Test Printer",
        manufacturer="Test",
        build_volume_mm=(200.0, 200.0, 200.0),
        nozzle_diameter_mm=0.4,
        allowed_layer_heights_mm=[0.2],
        min_feature_size_mm=0.4,
        native_bundle={backend_name: machine},
    )
    material = MaterialProfile(
        name="Test PLA",
        material="PLA",
        density_g_cm3=1.24,
        nozzle_temp_c=(190.0, 220.0),
        bed_temp_c=(45.0, 60.0),
        young_modulus_xy_mpa=3200.0,
        young_modulus_z_mpa=2100.0,
        poisson_ratio_xy=0.36,
        poisson_ratio_xz=0.33,
        shear_modulus_xz_mpa=850.0,
        tensile_strength_xy_mpa=55.0,
        tensile_strength_z_mpa=30.0,
        native_bundle={backend_name: filament},
    )
    process_profile = ProcessProfile(
        name="draft",
        layer_height_mm=0.2,
        infill_percent=15.0,
        supports=False,
        brim=False,
        wall_count=2,
        native_bundle={backend_name: process},
    )
    return printer, material, process_profile


def test_prusaslicer_nonzero_exit_with_gcode_present_is_a_warning_not_an_error(tmp_path, monkeypatch):
    printer, material, process = _profiles(tmp_path, "prusaslicer")
    input_model = tmp_path / "part.stl"
    input_model.write_text("solid\nendsolid\n")
    output_dir = tmp_path / "out"

    backend = PrusaSlicerBackend()
    monkeypatch.setattr(backend, "find_binary", lambda: Path("/fake/prusa-slicer"))
    monkeypatch.setattr(backend, "_version", lambda binary: "2.9.6")

    def fake_run_cli(binary, args, **kwargs):
        # Simulate PrusaSlicer's observed behavior: exits non-zero after an
        # advisory ("consider enabling supports/brim") but still writes G-code.
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "part.gcode").write_text("; fake gcode\n")
        return _fake_completed_process(returncode=1)

    monkeypatch.setattr(backend, "run_cli", fake_run_cli)

    request = SliceRequest(
        input_model=input_model,
        output_dir=output_dir,
        printer_profile=tmp_path / "printer.yaml",
        material_profile=tmp_path / "material.yaml",
    )
    result = backend.slice(request, printer=printer, material=material, process=process)

    assert result.status is Status.WARNING
    assert result.gcode_path is not None
    assert result.gcode_path.is_file()
    assert result.warnings


def test_orcaslicer_nonzero_exit_with_gcode_present_is_a_warning_not_an_error(tmp_path, monkeypatch):
    printer, material, process = _profiles(tmp_path, "orcaslicer")
    input_model = tmp_path / "part.stl"
    input_model.write_text("solid\nendsolid\n")
    output_dir = tmp_path / "out"

    backend = OrcaSlicerBackend()
    monkeypatch.setattr(backend, "find_binary", lambda: Path("/fake/OrcaSlicer"))
    monkeypatch.setattr(backend, "_version", lambda binary: "2.4.2")

    def fake_run_cli(binary, args, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "plate_1.gcode").write_text("; fake gcode\n")
        return _fake_completed_process(returncode=1)

    monkeypatch.setattr(backend, "run_cli", fake_run_cli)

    request = SliceRequest(
        input_model=input_model,
        output_dir=output_dir,
        printer_profile=tmp_path / "printer.yaml",
        material_profile=tmp_path / "material.yaml",
    )
    result = backend.slice(request, printer=printer, material=material, process=process)

    assert result.status is Status.WARNING
    assert result.gcode_path is not None
    assert result.gcode_path.is_file()
    assert result.warnings


def test_prusaslicer_missing_gcode_is_an_error_regardless_of_exit_code(tmp_path, monkeypatch):
    printer, material, process = _profiles(tmp_path, "prusaslicer")
    input_model = tmp_path / "part.stl"
    input_model.write_text("solid\nendsolid\n")
    output_dir = tmp_path / "out"

    backend = PrusaSlicerBackend()
    monkeypatch.setattr(backend, "find_binary", lambda: Path("/fake/prusa-slicer"))
    monkeypatch.setattr(backend, "_version", lambda binary: "2.9.6")
    monkeypatch.setattr(backend, "run_cli", lambda binary, args, **kwargs: _fake_completed_process(0))

    request = SliceRequest(
        input_model=input_model,
        output_dir=output_dir,
        printer_profile=tmp_path / "printer.yaml",
        material_profile=tmp_path / "material.yaml",
    )
    result = backend.slice(request, printer=printer, material=material, process=process)

    assert result.status is Status.ERROR


def test_bambu_nonzero_exit_with_gcode_present_is_a_warning_not_an_error(tmp_path, monkeypatch):
    printer, material, process = _profiles(tmp_path, "bambu")
    input_model = tmp_path / "part.stl"
    input_model.write_text("solid\nendsolid\n")
    output_dir = tmp_path / "out"

    backend = BambuStudioBackend()
    monkeypatch.setattr(backend, "find_binary", lambda: Path("/fake/BambuStudio"))
    monkeypatch.setattr(backend, "_version", lambda binary: "02.07.01.62")

    def fake_run_cli(binary, args, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "plate_1.gcode").write_text("; fake gcode\n")
        return _fake_completed_process(returncode=1)

    monkeypatch.setattr(backend, "run_cli", fake_run_cli)

    request = SliceRequest(
        input_model=input_model,
        output_dir=output_dir,
        printer_profile=tmp_path / "printer.yaml",
        material_profile=tmp_path / "material.yaml",
    )
    result = backend.slice(request, printer=printer, material=material, process=process)

    assert result.status is Status.WARNING
    assert result.gcode_path is not None
    assert result.gcode_path.is_file()
    assert result.warnings
