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

import json
import os
import shutil
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from printlab.cad import CadBuildError, CadBuildRequest, CadBuildResult, get_cad_backend
from printlab.cad.probe import classify_points, load_solid
from printlab.determinism import hash_artifact, hash_file
from printlab.evaluation import evaluate as evaluate_printability
from printlab.fea import analyze as analyze_fea
from printlab.fea import mesh_runner as fea_mesh_runner
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
    CadBuildReport,
    FEALoadCase,
    FEAMeshPreviewReport,
    FEAReport,
    GCodeReport,
    MaterialProfile,
    MeshRepairReport,
    MeshReport,
    OrientationSearchReport,
    PrintabilityReport,
    PrinterProfile,
    ProbedPoint,
    ProbeReport,
    ProcessProfile,
    RenderReport,
    RunManifest,
    SliceRequest,
    SliceResult,
)
from printlab.schemas.common import ArtifactError, Status
from printlab.slicing import get_backend

ARTIFACT_FILENAMES = {
    "step": "part.step",
    "stl": "part.stl",
    "build_fingerprint": ".build_fingerprint.json",
    "cad_build_report": "cad_build_report.json",
    "mesh_report": "mesh_report.json",
    "mesh_repair_report": "mesh_repair_report.json",
    "stl_repaired": "part_repaired.stl",
    "orientation_search_report": "orientation_search_report.json",
    "render_report": "render_report.json",
    "fea_report": "fea_report.json",
    "fea_mesh_preview_report": "fea_mesh_preview.json",
    "probe_report": "probe_report.json",
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
    source_path: Path
    printer_profile_path: Path
    material_profile_path: Path
    process_profile_path: Path
    cad_backend: str = "cadquery"
    build_function: str | None = "build"
    cad_options: dict = field(default_factory=dict)
    fea_load_case: FEALoadCase | None = None

    @property
    def part_py(self) -> Path:
        """Compatibility alias for callers written against the CadQuery-only API."""
        return self.source_path


#: Shown verbatim in load_part_config's missing-toml error, and used to
#: scaffold printlab_mcp.tools.printlab_init's output -- keep both in sync.
_MISSING_TOML_EXAMPLE = """\
[part]
name = "my_part"
module = "part.py"
function = "build"

[profiles]
printer = "profiles/printers/bambu_a1.yaml"
material = "profiles/materials/pla.yaml"
process = "profiles/processes/draft.yaml"
"""


def load_part_config(example_dir: Path, *, repo_root: Path | None = None) -> PartConfig:
    """Read `<example_dir>/printlab.toml`.

    `[profiles]` paths are resolved relative to `repo_root` -- which defaults
    to `Path.cwd()`, i.e. *this process's* working directory at the time this
    function runs, not `example_dir`'s location. For a `printlab-mcp` server
    launched via `uv --directory <path> run printlab-mcp`, that's fixed at
    server-launch time to `<path>`; call `printlab_doctor` (over MCP) or
    `printlab doctor` (CLI) to confirm what it resolved to.
    """
    example_dir = Path(example_dir).resolve()
    repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    config_path = example_dir / "printlab.toml"
    if not config_path.is_file():
        raise PipelineError(
            f"missing printlab.toml in {example_dir}\n\n"
            "A minimal valid printlab.toml looks like:\n\n"
            f"{_MISSING_TOML_EXAMPLE}\n"
            "(scaffold one automatically with printlab_init over MCP, or hand-write "
            "one following an existing example, e.g. examples/bracket/printlab.toml)"
        )

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)
    part = data["part"]
    profiles = data["profiles"]
    fea_table = data.get("fea")
    cad_backend = part.get("cad_backend", "cadquery")
    try:
        get_cad_backend(cad_backend)
    except CadBuildError as exc:
        raise PipelineError(str(exc)) from exc
    if cad_backend != "cadquery" and "function" in part:
        raise PipelineError(f"[part].function is only valid for the cadquery backend, not {cad_backend}")
    source = part.get("source", part.get("module"))
    if source is None:
        raise PipelineError("[part] must define `source` (or legacy `module`)")
    return PartConfig(
        name=part["name"],
        example_dir=example_dir,
        source_path=example_dir / source,
        cad_backend=cad_backend,
        build_function=part.get("function", "build") if cad_backend == "cadquery" else None,
        cad_options=dict(part.get(cad_backend, {})),
        fea_load_case=FEALoadCase(**fea_table) if fea_table else None,
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


def _write_json_atomic_raw(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
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


def _build_request(config: PartConfig, output_dir: Path) -> CadBuildRequest:
    return CadBuildRequest(
        source_path=config.source_path,
        output_dir=output_dir,
        build_target=config.build_function,
        options=config.cad_options,
    )


def _build_fingerprint(config: PartConfig, result: CadBuildResult | None = None) -> dict:
    dependencies = result.dependencies if result and result.dependencies else (config.source_path,)
    return {
        "cad_backend": config.cad_backend,
        "cad_options": config.cad_options,
        "cad_source_sha256": hash_file(config.source_path),
        "build_function": config.build_function,
        "source_path": str(config.source_path),
        "dependency_sha256": {str(path): hash_file(path) for path in dependencies},
        "tool_versions": result.tool_versions if result else {},
    }


def build_is_fresh(config: PartConfig, output_dir: Path) -> bool:
    """Whether `output_dir` already holds a build that matches `config`'s
    current CAD source content and build function -- i.e. whether a caller can
    reuse it instead of re-running `stage_build`.

    Backs printlab_mcp.tools.ensure_built's rebuild decision (issue #5.1: it
    used to check only whether `part.stl` existed, so an edited `part.py` or a
    `[part].function` switch could silently reuse a stale build). Missing or
    unreadable fingerprint, or a missing CAD source file, counts as not fresh
    (forces a rebuild rather than risking a false "fresh").
    """
    output_dir = Path(output_dir)
    fingerprint_path = output_dir / ARTIFACT_FILENAMES["build_fingerprint"]
    required_outputs = (output_dir / ARTIFACT_FILENAMES["step"], output_dir / ARTIFACT_FILENAMES["stl"])
    if (
        not fingerprint_path.is_file()
        or not config.source_path.is_file()
        or not all(path.is_file() for path in required_outputs)
    ):
        return False
    try:
        recorded = json.loads(fingerprint_path.read_text())
    except json.JSONDecodeError:
        return False
    if not isinstance(recorded, dict):
        return False
    current = _build_fingerprint(config)
    for key in ("cad_backend", "cad_options", "cad_source_sha256", "build_function", "source_path"):
        if recorded.get(key) != current[key]:
            return False
    dependency_hashes = recorded.get("dependency_sha256")
    if (
        not isinstance(dependency_hashes, dict)
        or not dependency_hashes
        or not all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in dependency_hashes.items()
        )
    ):
        return False
    try:
        if any(
            not Path(path).is_file() or hash_file(Path(path)) != digest
            for path, digest in dependency_hashes.items()
        ):
            return False
        backend = get_cad_backend(config.cad_backend)
        tool_versions = backend.tool_versions(_build_request(config, output_dir))
    except (OSError, CadBuildError):
        return False
    return recorded.get("tool_versions", {}) == tool_versions


def stage_build(config: PartConfig, output_dir: Path) -> tuple[Path, Path]:
    backend = get_cad_backend(config.cad_backend)
    report_path = output_dir / ARTIFACT_FILENAMES["cad_build_report"]
    try:
        result = backend.build(_build_request(config, output_dir))
    except CadBuildError as exc:
        _write_json_atomic(
            report_path,
            CadBuildReport(
                status=Status.ERROR,
                errors=[
                    ArtifactError(code=exc.code, message=str(exc), stage="build", context=exc.context)
                ],
                backend_name=config.cad_backend,
                source_path=str(config.source_path),
            ),
        )
        raise
    _write_json_atomic(
        report_path,
        CadBuildReport(
            backend_name=result.backend_name,
            source_path=str(config.source_path),
            step_path=str(result.step_path),
            stl_path=str(result.stl_path),
            dependencies=[str(path) for path in result.dependencies],
            tool_versions=result.tool_versions,
            settings=result.settings,
            metadata=result.metadata,
        ),
    )
    _write_json_atomic_raw(
        output_dir / ARTIFACT_FILENAMES["build_fingerprint"], _build_fingerprint(config, result)
    )
    return result.step_path, result.stl_path


def _read_cad_build_report(output_dir: Path) -> CadBuildReport:
    return CadBuildReport.model_validate_json(
        (output_dir / ARTIFACT_FILENAMES["cad_build_report"]).read_text()
    )


def _cad_manifest_inputs(report: CadBuildReport, stl_path: Path) -> dict[str, Path]:
    inputs = {"cad_source": Path(report.source_path), "stl": stl_path}
    source = Path(report.source_path).resolve()
    dependency_index = 1
    for dependency in report.dependencies:
        path = Path(dependency)
        if path.resolve() == source:
            continue
        inputs[f"cad_dependency_{dependency_index}"] = path
        dependency_index += 1
    return inputs


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
    layout: Literal["separate", "grid"] = "separate",
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
    rebuilt: bool = False,
) -> RenderReport:
    """Not part of `run_all()`'s critical path (like stage_repair/
    stage_orientation_search): an explicit, image-producing capability. The
    PNGs themselves are not part of the reproducibility contract -- only this
    JSON's camera metadata is (see printlab.schemas.rendering). `layout="grid"`
    tiles up to 4 views into one composited PNG; `focus_center`/`focus_radius`
    zoom into a fixed region instead of framing the whole mesh. `rebuilt`
    records whether the caller rebuilt the CAD source for this render (see
    RenderReport.rebuilt) -- purely descriptive, not acted on here.
    """
    report = render_part(
        stl_path,
        output_dir,
        views=views,
        width_px=width_px,
        height_px=height_px,
        layout=layout,
        focus_center=focus_center,
        focus_radius=focus_radius,
        rebuilt=rebuilt,
    )
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["render_report"], report)
    return report


def stage_fea(
    step_path: Path,
    output_dir: Path,
    *,
    load_case: FEALoadCase,
    material: MaterialProfile,
    build_direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> FEAReport:
    """Not part of `run_all()`'s critical path (like stage_repair/
    stage_orientation_search/stage_render): explicit linear-static FEA via
    CalculiX. Requires the `fea` extra (gmsh) and `ccx` on PATH -- see
    printlab.fea for the crude-but-real, placeholder-material caveats.
    """
    try:
        report = analyze_fea(step_path, load_case, material, build_direction=build_direction)
    except (FileNotFoundError, RuntimeError, ModuleNotFoundError) as exc:
        raise PipelineError(f"FEA failed: {exc}") from exc
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["fea_report"], report)
    return report


def stage_fea_preview(
    step_path: Path, output_dir: Path, *, mesh_size_mm: float | None = None
) -> FEAMeshPreviewReport:
    """Mesh-only, `ccx`-free pre-flight ahead of `stage_fea` (issue #5.2): can
    `mesh_size_mm` (or the diagonal-based default) mesh this part's geometry at
    all? Meshing runs in the same isolated subprocess as a real FEA run (see
    printlab.fea.mesh_runner), so a Gmsh-level failure comes back as a
    `status="error"` report with a structured `errors[]` entry -- never an
    exception -- making this safe to try before a real `printlab_fea` call on
    an unfamiliar part.
    """
    step_path = Path(step_path)
    input_sha256 = hash_file(step_path)
    try:
        _nodes, elements, resolved_mesh_size_mm = fea_mesh_runner.run_mesh_worker(
            step_path, mesh_size_mm=mesh_size_mm
        )
    except (RuntimeError, ModuleNotFoundError) as exc:
        report = FEAMeshPreviewReport(
            status=Status.ERROR,
            errors=[ArtifactError(code="mesh_failed", message=str(exc), stage="fea_preview")],
            input_path=step_path,
            input_sha256=input_sha256,
            mesh_size_mm=mesh_size_mm,
        )
        _write_json_atomic(output_dir / ARTIFACT_FILENAMES["fea_mesh_preview_report"], report)
        return report

    report = FEAMeshPreviewReport(
        input_path=step_path,
        input_sha256=input_sha256,
        mesh_size_mm=mesh_size_mm,
        resolved_mesh_size_mm=resolved_mesh_size_mm,
        mesh_node_count=int(_nodes.shape[0]),
        mesh_element_count=int(elements.shape[0]),
    )
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["fea_mesh_preview_report"], report)
    return report


def stage_probe(
    step_path: Path, output_dir: Path, *, points: Sequence[tuple[float, float, float]], tolerance_mm: float
) -> ProbeReport:
    """Classify each of `points` as "IN"/"OUT"/"ON" the built solid (issue
    #5.3): brings the ad hoc "is this point inside the built solid" scripting
    pattern into a structured, deterministic report. Reads `step_path` back
    from disk (the exact B-rep, not the tessellated STL) rather than
    rebuilding, matching every other independently-executable stage's
    convention of reading its upstream artifact.
    """
    step_path = Path(step_path)
    input_sha256 = hash_file(step_path)
    shape = load_solid(step_path)
    classifications = classify_points(shape, list(points), tolerance_mm=tolerance_mm)
    report = ProbeReport(
        input_path=step_path,
        input_sha256=input_sha256,
        tolerance_mm=tolerance_mm,
        points=[
            ProbedPoint(point_mm=point, classification=classification)
            for point, classification in zip(points, classifications, strict=True)
        ],
    )
    _write_json_atomic(output_dir / ARTIFACT_FILENAMES["probe_report"], report)
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


def run_all(
    example_dir: Path,
    backend_name: str,
    *,
    output_dir: Path | None = None,
    build_function: str | None = None,
) -> dict:
    """Run every stage in order and return the in-memory artifacts + manifest.

    `build_function` overrides printlab.toml's `[part].function` for this call
    only (issue #5.4) -- e.g. to check an alternate builder in the same CAD
    module without editing the config file back and forth.
    """
    config = load_part_config(example_dir)
    if build_function is not None:
        config = replace(config, build_function=build_function)
    output_dir = Path(output_dir) if output_dir else default_output_dir(config, backend_name)
    prepare_output_dir(output_dir, clean=True)

    printer, material, process = load_profiles(config)

    step_path, stl_path = stage_build(config, output_dir)
    cad_build = _read_cad_build_report(output_dir)
    mesh = stage_mesh(stl_path, output_dir)
    slice_result = stage_slice(
        config, stl_path, output_dir, backend_name, printer=printer, material=material, process=process
    )
    if slice_result.status.value == "error":
        manifest = build_run_manifest(
            tool_versions=cad_build.tool_versions,
            input_hashes=hash_inputs(_cad_manifest_inputs(cad_build, stl_path)),
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
        tool_versions={**cad_build.tool_versions, backend_name: slice_result.backend_version},
        input_hashes=hash_inputs(_cad_manifest_inputs(cad_build, stl_path)),
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
            "cad_build_report": hash_artifact(cad_build),
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
        "cad_build": cad_build,
        "mesh": mesh,
        "slice_result": slice_result,
        "gcode": gcode,
        "printability": printability,
        "manifest": manifest,
        "report_path": report_path,
    }


def run_check(
    example_dir: Path, *, output_dir: Path | None = None, build_function: str | None = None
) -> dict:
    """Run build -> mesh -> evaluate -> report with slicing skipped entirely.

    Distinct from `run_all()`, which keeps its full-fidelity contract and
    still requires a working slicer: the mesh-derived printability checks
    (manifold, build-volume fit, wall thickness) don't need one, so this is
    the "the core doesn't need a slicer" path (see docs/environment.md).
    Slicer-derived metrics (filament mass, print time, layer count) come back
    `None` -- see printlab.evaluation.printability.

    `build_function` overrides printlab.toml's `[part].function` for this call
    only -- see run_all's matching parameter (issue #5.4).
    """
    config = load_part_config(example_dir)
    if build_function is not None:
        config = replace(config, build_function=build_function)
    output_dir = Path(output_dir) if output_dir else default_output_dir(config, "check")
    prepare_output_dir(output_dir, clean=True)

    printer, _, _ = load_profiles(config)

    step_path, stl_path = stage_build(config, output_dir)
    cad_build = _read_cad_build_report(output_dir)
    mesh = stage_mesh(stl_path, output_dir)
    printability = stage_evaluate(mesh, None, output_dir, printer=printer)

    manifest = build_run_manifest(
        tool_versions=cad_build.tool_versions,
        input_hashes=hash_inputs(_cad_manifest_inputs(cad_build, stl_path)),
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
            "cad_build_report": hash_artifact(cad_build),
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
        "cad_build": cad_build,
        "mesh": mesh,
        "printability": printability,
        "manifest": manifest,
        "report_path": report_path,
    }
