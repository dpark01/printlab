"""Stage orchestration and the output-directory contract.

`run_all()` writes a fresh, deterministic output directory: existing contents
are cleared first (clean-slate -- a re-run never blends stale artifacts with
new ones), and every artifact is written atomically (temp file + rename) so a
crash mid-run can never leave a half-written JSON file behind. Each stage
function is independently callable too (SETUP.md: "every stage must be
independently executable") -- if given no in-memory input it reads the
upstream artifact back from `output_dir`.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from printlab.cad import build_part, export_step, export_stl
from printlab.determinism import hash_artifact
from printlab.evaluation import evaluate as evaluate_printability
from printlab.gcode import analyze as analyze_gcode
from printlab.mesh import analyze as analyze_mesh
from printlab.mesh import orient as search_orientation
from printlab.mesh import repair as repair_mesh
from printlab.profiles import load_material_profile, load_printer_profile, load_process_profile
from printlab.provenance import build_run_manifest, finalize_manifest, hash_inputs
from printlab.rendering import DEFAULT_VIEWS, CameraView
from printlab.rendering import render as render_part
from printlab.reporting import render_html, render_markdown
from printlab.schemas import (
    GCodeReport,
    MaterialProfile,
    MeshRepairReport,
    MeshReport,
    OrientationSearchReport,
    PrintabilityReport,
    PrinterProfile,
    ProcessProfile,
    RenderReport,
    RunManifest,
    SliceRequest,
    SliceResult,
)
from printlab.slicing import get_backend

ARTIFACT_FILENAMES = {
    "step": "part.step",
    "stl": "part.stl",
    "mesh_report": "mesh_report.json",
    "mesh_repair_report": "mesh_repair_report.json",
    "stl_repaired": "part_repaired.stl",
    "orientation_search_report": "orientation_search_report.json",
    "render_report": "render_report.json",
    "slice_result": "slice_result.json",
    "gcode_report": "gcode_report.json",
    "printability_report": "printability_report.json",
    "report": "report.md",
    "report_html": "report.html",
    "run_manifest": "run_manifest.json",
}


class PipelineError(RuntimeError):
    """Raised when a stage can't proceed (e.g. a required upstream artifact is missing)."""


@dataclass(frozen=True)
class PartConfig:
    name: str
    example_dir: Path
    part_py: Path
    build_function: str
    printer_profile_path: Path
    material_profile_path: Path
    process_profile_path: Path


def load_part_config(example_dir: Path, *, repo_root: Path | None = None) -> PartConfig:
    """Read `<example_dir>/printlab.toml`. Profile paths are relative to repo_root."""
    example_dir = Path(example_dir).resolve()
    repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    config_path = example_dir / "printlab.toml"
    if not config_path.is_file():
        raise PipelineError(f"missing printlab.toml in {example_dir}")

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)
    part = data["part"]
    profiles = data["profiles"]
    return PartConfig(
        name=part["name"],
        example_dir=example_dir,
        part_py=example_dir / part["module"],
        build_function=part.get("function", "build"),
        printer_profile_path=repo_root / profiles["printer"],
        material_profile_path=repo_root / profiles["material"],
        process_profile_path=repo_root / profiles["process"],
    )


def default_output_dir(config: PartConfig, backend_name: str) -> Path:
    return config.example_dir / "output" / backend_name


def prepare_output_dir(output_dir: Path, *, clean: bool) -> Path:
    output_dir = Path(output_dir)
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _write_json_atomic(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(model.model_dump_json(indent=2) + "\n")
    os.replace(tmp_path, path)


def read_json_artifact(path: Path, model_cls: type[BaseModel]) -> BaseModel:
    """Read a previously-written artifact back, for independently-run stages."""
    if not path.is_file():
        raise PipelineError(f"required upstream artifact missing: {path}")
    return model_cls.model_validate_json(path.read_text())


def load_profiles(config: PartConfig) -> tuple[PrinterProfile, MaterialProfile, ProcessProfile]:
    return (
        load_printer_profile(config.printer_profile_path),
        load_material_profile(config.material_profile_path),
        load_process_profile(config.process_profile_path),
    )


def stage_build(config: PartConfig, output_dir: Path) -> tuple[Path, Path]:
    result = build_part(config.part_py, config.build_function)
    step_path = export_step(result, output_dir / ARTIFACT_FILENAMES["step"])
    stl_path = export_stl(result, output_dir / ARTIFACT_FILENAMES["stl"])
    return step_path, stl_path


def stage_mesh(stl_path: Path, output_dir: Path) -> MeshReport:
    report = analyze_mesh(stl_path)
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["mesh_report"], report)
    return report


def stage_repair(stl_path: Path, output_dir: Path) -> MeshRepairReport:
    """Not part of `run_all()`'s critical path: CadQuery-sourced STLs are
    already clean by construction (see printlab.mesh.repair docstring), so
    this is an explicitly-invoked capability for STL input PrintLab doesn't
    control the origin of, not an automatic step in the standard pipeline.
    """
    output_path = output_dir / ARTIFACT_FILENAMES["stl_repaired"]
    report = repair_mesh(stl_path, output_path=output_path)
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["mesh_repair_report"], report)
    return report


def stage_orientation_search(stl_path: Path, output_dir: Path) -> OrientationSearchReport:
    """Not part of `run_all()`'s critical path (like stage_repair): explicit
    orchestration over B.6-B.8's metrics, mesh-metrics-only ranking (no
    re-slicing candidates -- see SETUP.md B.9).
    """
    report = search_orientation(stl_path)
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["orientation_search_report"], report)
    return report


def stage_render(
    stl_path: Path,
    output_dir: Path,
    *,
    views: Sequence[str | CameraView] = DEFAULT_VIEWS,
    width_px: int = 800,
    height_px: int = 600,
) -> RenderReport:
    """Not part of `run_all()`'s critical path (like stage_repair/
    stage_orientation_search): an explicit, image-producing capability. The
    PNGs themselves are not part of the reproducibility contract -- only this
    JSON's camera metadata is (see printlab.schemas.rendering).
    """
    report = render_part(stl_path, output_dir, views=views, width_px=width_px, height_px=height_px)
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["render_report"], report)
    return report


def stage_slice(
    config: PartConfig,
    stl_path: Path,
    output_dir: Path,
    backend_name: str,
    *,
    printer: PrinterProfile,
    material: MaterialProfile,
    process: ProcessProfile,
) -> SliceResult:
    backend = get_backend(backend_name)
    request = SliceRequest(
        input_model=stl_path,
        output_dir=output_dir,
        printer_profile=config.printer_profile_path,
        material_profile=config.material_profile_path,
        process_profile=config.process_profile_path,
    )
    result = backend.slice(request, printer=printer, material=material, process=process)
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["slice_result"], result)
    return result


def stage_gcode(slice_result: SliceResult, output_dir: Path, *, material: MaterialProfile) -> GCodeReport:
    if slice_result.gcode_path is None:
        raise PipelineError("slice_result has no gcode_path; slicing must have failed")
    report = analyze_gcode(
        slice_result.gcode_path,
        backend=slice_result.backend,
        material_density_g_cm3=material.density_g_cm3,
    )
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["gcode_report"], report)
    return report


def stage_evaluate(
    mesh: MeshReport, gcode: GCodeReport | None, output_dir: Path, *, printer: PrinterProfile
) -> PrintabilityReport:
    report = evaluate_printability(mesh, gcode, printer)
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["printability_report"], report)
    return report


def stage_report(
    config: PartConfig,
    mesh: MeshReport,
    slice_result: SliceResult | None,
    gcode: GCodeReport | None,
    printability: PrintabilityReport,
    manifest: RunManifest,
    output_dir: Path,
) -> Path:
    text = render_markdown(
        part_name=config.name,
        mesh=mesh,
        slice_result=slice_result,
        gcode=gcode,
        printability=printability,
        manifest=manifest,
    )
    report_path = output_dir / ARTIFACT_FILENAMES["report"]
    report_path.write_text(text)

    html_text = render_html(
        part_name=config.name,
        mesh=mesh,
        slice_result=slice_result,
        gcode=gcode,
        printability=printability,
        manifest=manifest,
    )
    (output_dir / ARTIFACT_FILENAMES["report_html"]).write_text(html_text)

    return report_path


def run_all(example_dir: Path, backend_name: str, *, output_dir: Path | None = None) -> dict:
    """Run every stage in order and return the in-memory artifacts + manifest."""
    config = load_part_config(example_dir)
    output_dir = Path(output_dir) if output_dir else default_output_dir(config, backend_name)
    prepare_output_dir(output_dir, clean=True)

    printer, material, process = load_profiles(config)

    step_path, stl_path = stage_build(config, output_dir)
    mesh = stage_mesh(stl_path, output_dir)
    slice_result = stage_slice(
        config, stl_path, output_dir, backend_name, printer=printer, material=material, process=process
    )
    if slice_result.status.value == "error":
        manifest = build_run_manifest(
            input_hashes=hash_inputs({"cad_source": config.part_py, "stl": stl_path}),
            profile_hashes=hash_inputs(
                {
                    "printer": config.printer_profile_path,
                    "material": config.material_profile_path,
                    "process": config.process_profile_path,
                }
            ),
        )
        _write_json_atomic(output_dir / ARTIFACT_FILENAMES["run_manifest"], manifest)
        raise PipelineError(
            f"slicing failed: {slice_result.errors[0].message if slice_result.errors else 'unknown error'}"
        )

    gcode = stage_gcode(slice_result, output_dir, material=material)
    printability = stage_evaluate(mesh, gcode, output_dir, printer=printer)

    manifest = build_run_manifest(
        tool_versions={backend_name: slice_result.backend_version},
        input_hashes=hash_inputs({"cad_source": config.part_py, "stl": stl_path}),
        profile_hashes=hash_inputs(
            {
                "printer": config.printer_profile_path,
                "material": config.material_profile_path,
                "process": config.process_profile_path,
            }
        ),
        resolved_settings=slice_result.resolved_settings,
    )
    manifest = finalize_manifest(
        manifest,
        {
            "mesh_report": hash_artifact(mesh),
            "slice_result": hash_artifact(slice_result),
            "gcode_report": hash_artifact(gcode),
            "printability_report": hash_artifact(printability),
        },
    )
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["run_manifest"], manifest)
    report_path = stage_report(config, mesh, slice_result, gcode, printability, manifest, output_dir)

    return {
        "output_dir": output_dir,
        "step_path": step_path,
        "stl_path": stl_path,
        "mesh": mesh,
        "slice_result": slice_result,
        "gcode": gcode,
        "printability": printability,
        "manifest": manifest,
        "report_path": report_path,
    }


def run_check(example_dir: Path, *, output_dir: Path | None = None) -> dict:
    """Run build -> mesh -> evaluate -> report with slicing skipped entirely.

    Distinct from `run_all()`, which keeps its full-fidelity contract and
    still requires a working slicer: the mesh-derived printability checks
    (manifold, build-volume fit, wall thickness) don't need one, so this is
    the "the core doesn't need a slicer" path (see docs/environment.md).
    Slicer-derived metrics (filament mass, print time, layer count) come back
    `None` -- see printlab.evaluation.printability.
    """
    config = load_part_config(example_dir)
    output_dir = Path(output_dir) if output_dir else default_output_dir(config, "check")
    prepare_output_dir(output_dir, clean=True)

    printer, _, _ = load_profiles(config)

    step_path, stl_path = stage_build(config, output_dir)
    mesh = stage_mesh(stl_path, output_dir)
    printability = stage_evaluate(mesh, None, output_dir, printer=printer)

    manifest = build_run_manifest(
        input_hashes=hash_inputs({"cad_source": config.part_py, "stl": stl_path}),
        profile_hashes=hash_inputs(
            {
                "printer": config.printer_profile_path,
                "material": config.material_profile_path,
                "process": config.process_profile_path,
            }
        ),
    )
    manifest = finalize_manifest(
        manifest,
        {
            "mesh_report": hash_artifact(mesh),
            "printability_report": hash_artifact(printability),
        },
    )
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["run_manifest"], manifest)
    report_path = stage_report(config, mesh, None, None, printability, manifest, output_dir)

    return {
        "output_dir": output_dir,
        "step_path": step_path,
        "stl_path": stl_path,
        "mesh": mesh,
        "printability": printability,
        "manifest": manifest,
        "report_path": report_path,
    }
