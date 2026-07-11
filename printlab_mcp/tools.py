"""PrintLab capabilities as plain functions, importing only `printlab`.

Kept free of any `fastmcp` import so it is unit-testable without the optional
MCP dependency installed; `server.py` wraps these and owns the MCP-specific
error translation. Failures propagate as `pipeline.PipelineError` (or
`printlab.cad.PartBuildError`) rather than being swallowed here.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import Literal

from printlab import pipeline
from printlab.rendering import DEFAULT_VIEWS, CameraView
from printlab.schemas import (
    ExportedFile,
    ExportReport,
    FEAMeshPreviewReport,
    FEAReport,
    OrientationSearchReport,
    PrintabilityReport,
    RenderReport,
    SliceResult,
)
from printlab.schemas.common import ArtifactError, Status
from printlab.schemas.diff import CheckStatusChange, MetricDelta, MetricsDiffReport
from printlab.schemas.probe import ProbeReport

#: Mirrors printlab.cli.main._BACKEND_TOOL_KEY: a backend's short name differs
#: from its tools.toml key for bambu (backend "bambu" vs pinned "bambustudio").
_BACKEND_TOOL_KEY = {"prusaslicer": "prusaslicer", "bambu": "bambustudio"}

#: layout="grid"'s default view set when the caller doesn't override `views`
#: -- the standard "three-view + iso" engineering-drawing layout, distinct
#: from DEFAULT_VIEWS (which is tuned for layout="separate").
_GRID_DEFAULT_VIEWS: tuple[str, ...] = ("top", "front", "right", "iso")

# "check" is a no-slicer sentinel accepted by every `backend` parameter
# below, not a real slicer backend -- it skips slicing entirely (see
# printlab.pipeline.run_check). Real backends: "prusaslicer", "bambu". See
# each printlab_mcp.server tool's docstring for the client-visible version
# of this note (F1: this fact needs to reach an MCP client, not just source).


def ensure_built(
    example_dir: Path,
    backend: str,
    *,
    output_dir: Path | str | None = None,
    function: str | None = None,
) -> tuple[pipeline.PartConfig, Path, bool]:
    """Build if part.stl isn't present yet, or the existing build is stale
    (edited CAD source, or a different `function` than what built it -- see
    pipeline.build_is_fresh); return the resolved PartConfig, the output_dir
    actually used, and whether a rebuild happened this call.

    `function` overrides printlab.toml's `[part].function` for this call only
    (issue #5.4) -- switching build targets composes with the freshness check
    above: requesting a different function makes the existing build stale, so
    it rebuilds automatically instead of silently reusing the wrong target.
    """
    config = pipeline.load_part_config(Path(example_dir))
    if function is not None:
        config = replace(config, build_function=function)
    resolved_output_dir = Path(output_dir) if output_dir else pipeline.default_output_dir(config, backend)
    stl_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    rebuilt = not stl_path.is_file() or not pipeline.build_is_fresh(config, resolved_output_dir)
    if rebuilt:
        pipeline.prepare_output_dir(resolved_output_dir, clean=False)
        pipeline.stage_build(config, resolved_output_dir)
    return config, resolved_output_dir, rebuilt


def printlab_check(
    example_dir: str, output_dir: str | None = None, function: str | None = None
) -> PrintabilityReport:
    """Run build -> mesh -> evaluate -> report with slicing skipped."""
    return pipeline.run_check(
        Path(example_dir), output_dir=Path(output_dir) if output_dir else None, build_function=function
    )["printability"]


def printlab_all(
    example_dir: str,
    backend: str = "prusaslicer",
    output_dir: str | None = None,
    function: str | None = None,
) -> PrintabilityReport:
    """Run the full pipeline: build -> mesh -> slice -> gcode -> evaluate -> report."""
    return pipeline.run_all(
        Path(example_dir),
        backend,
        output_dir=Path(output_dir) if output_dir else None,
        build_function=function,
    )["printability"]


def printlab_orient(
    example_dir: str, backend: str = "check", output_dir: str | None = None, function: str | None = None
) -> OrientationSearchReport:
    """Try axis-aligned rotations of part.stl and recommend one."""
    _config, resolved_output_dir, _rebuilt = ensure_built(
        Path(example_dir), backend, output_dir=output_dir, function=function
    )
    stl_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    return pipeline.stage_orientation_search(stl_path, resolved_output_dir)


def printlab_render(
    example_dir: str,
    views: list[str] | None = None,
    backend: str = "check",
    elevation: float | None = None,
    azimuth: float | None = None,
    layout: Literal["separate", "grid"] = "separate",
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
    output_dir: str | None = None,
    function: str | None = None,
) -> RenderReport:
    """Render part.stl to PNG(s) from named camera views."""
    _config, resolved_output_dir, rebuilt = ensure_built(
        Path(example_dir), backend, output_dir=output_dir, function=function
    )
    stl_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["stl"]

    resolved_views: list[str | CameraView]
    if elevation is not None and azimuth is not None:
        # Mirrors printlab.cli.main.render's elevation/azimuth branch exactly:
        # only fires when BOTH are given; a lone one is ignored in favor of `views`.
        resolved_views = [CameraView("custom", elevation, azimuth)]
    elif views is not None:
        resolved_views = views
    else:
        resolved_views = list(_GRID_DEFAULT_VIEWS) if layout == "grid" else list(DEFAULT_VIEWS)

    return pipeline.stage_render(
        stl_path,
        resolved_output_dir,
        views=resolved_views,
        layout=layout,
        focus_center=focus_center,
        focus_radius=focus_radius,
        rebuilt=rebuilt,
    )


def printlab_fea(
    example_dir: str, backend: str = "check", output_dir: str | None = None, function: str | None = None
) -> FEAReport:
    """Run a linear-static FEA (CalculiX) using printlab.toml's [fea] load
    case. Requires the `fea` extra (gmsh) and `ccx` on PATH."""
    config, resolved_output_dir, _rebuilt = ensure_built(
        Path(example_dir), backend, output_dir=output_dir, function=function
    )
    if config.fea_load_case is None:
        raise pipeline.PipelineError(
            f"{example_dir} has no [fea] load case in printlab.toml -- printlab_fea requires one "
            "(a [fea] table with load_point_mm/load_force_n/load_region_radius_mm; see "
            "examples/hook/printlab.toml for a worked example, or call printlab_describe first "
            "to check whether one is configured)."
        )
    step_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["step"]
    _, material, _ = pipeline.load_profiles(config)
    return pipeline.stage_fea(
        step_path, resolved_output_dir, load_case=config.fea_load_case, material=material
    )


def printlab_fea_preview(
    example_dir: str,
    backend: str = "check",
    mesh_size_mm: float | None = None,
    output_dir: str | None = None,
    function: str | None = None,
) -> FEAMeshPreviewReport:
    """Mesh-only, `ccx`-free pre-flight ahead of printlab_fea: reports whether
    `mesh_size_mm` (or the default heuristic) can mesh the part's geometry at
    all, without running a full FEA. Does not require a [fea] load case in
    printlab.toml (meshing needs only the built part.step) -- unlike
    printlab_fea, this works on any buildable part. Meshing runs in the same
    isolated subprocess as a real FEA run, so a meshing failure comes back as
    a structured `status="error"` report, never a crash (see printlab_fea's
    docstring and issue #4)."""
    _config, resolved_output_dir, _rebuilt = ensure_built(
        Path(example_dir), backend, output_dir=output_dir, function=function
    )
    step_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["step"]
    return pipeline.stage_fea_preview(step_path, resolved_output_dir, mesh_size_mm=mesh_size_mm)


def printlab_probe(
    example_dir: str,
    points: list[tuple[float, float, float]],
    backend: str = "check",
    tolerance_mm: float = 1e-6,
    output_dir: str | None = None,
    function: str | None = None,
) -> ProbeReport:
    """Classify each of `points` (x, y, z in mm, the part's native coordinate
    frame) as "IN"/"OUT"/"ON" the built solid -- e.g. to confirm a hinge fold
    or snap-latch's resting position actually lands where intended, without a
    one-off OCP script. Classifies against the exact CAD boundary
    representation (part.step), not the tessellated STL."""
    _config, resolved_output_dir, _rebuilt = ensure_built(
        Path(example_dir), backend, output_dir=output_dir, function=function
    )
    step_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["step"]
    return pipeline.stage_probe(step_path, resolved_output_dir, points=points, tolerance_mm=tolerance_mm)


#: Which export format copies from where in output/<backend>/, and the
#: destination filename extension. "render" is handled separately (it fans
#: out to every render_*.png present, not a single fixed source).
_EXPORT_SINGLE_FILE_FORMATS: dict[str, tuple[str, str]] = {
    "stl": (pipeline.ARTIFACT_FILENAMES["stl"], "stl"),
    "step": (pipeline.ARTIFACT_FILENAMES["step"], "step"),
    "3mf": ("part.3mf", "3mf"),
}

_DEFAULT_EXPORT_FORMATS: tuple[str, ...] = ("stl", "step")


def printlab_export(
    example_dir: str,
    backend: str,
    dest_dir: str,
    formats: list[str] | None = None,
    name_prefix: str | None = None,
) -> ExportReport:
    """Copy named deliverables (STL/STEP/3MF/G-code/renders) out of the
    disposable `output/<backend>/` tree into `dest_dir`, renamed to
    `{name_prefix or the part's name}.<ext>` -- the "here are the final
    files" step that otherwise required hand-copying files out with new
    names. Does not build anything itself: run printlab_check/_all/_render
    first for whichever formats you're requesting. A requested format whose
    source doesn't exist yet (e.g. `gcode` without a prior printlab_all) is
    recorded as a warning, not a hard failure -- the rest still get copied."""
    config = pipeline.load_part_config(Path(example_dir))
    resolved_output_dir = pipeline.default_output_dir(config, backend)
    resolved_formats = list(formats) if formats else list(_DEFAULT_EXPORT_FORMATS)
    prefix = name_prefix or config.name
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    exported: list[ExportedFile] = []
    errors: list[ArtifactError] = []

    for fmt in resolved_formats:
        if fmt == "render":
            render_pngs = sorted(resolved_output_dir.glob("render_*.png"))
            if not render_pngs:
                errors.append(
                    ArtifactError(
                        code="export_source_missing",
                        message=(
                            f"no render_*.png in {resolved_output_dir} -- call printlab_render "
                            "against this example_dir/backend before exporting 'render'"
                        ),
                        stage="export",
                        context={"format": fmt},
                    )
                )
                continue
            for png in render_pngs:
                dest_path = dest / f"{prefix}_{png.stem}.png"
                shutil.copy2(png, dest_path)
                exported.append(ExportedFile(format="render", source=png, dest=dest_path))
            continue

        if fmt == "gcode":
            slice_result_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["slice_result"]
            if not slice_result_path.is_file():
                errors.append(
                    ArtifactError(
                        code="export_source_missing",
                        message=(
                            f"no slice_result.json in {resolved_output_dir} -- call printlab_all "
                            "against this example_dir/backend before exporting 'gcode'"
                        ),
                        stage="export",
                        context={"format": fmt},
                    )
                )
                continue
            slice_result = pipeline.read_json_artifact(slice_result_path, SliceResult)
            if slice_result.gcode_path is None or not slice_result.gcode_path.is_file():
                errors.append(
                    ArtifactError(
                        code="export_source_missing",
                        message=f"slice_result.json in {resolved_output_dir} has no gcode_path",
                        stage="export",
                        context={"format": fmt},
                    )
                )
                continue
            dest_path = dest / f"{prefix}.gcode"
            shutil.copy2(slice_result.gcode_path, dest_path)
            exported.append(ExportedFile(format="gcode", source=slice_result.gcode_path, dest=dest_path))
            continue

        if fmt not in _EXPORT_SINGLE_FILE_FORMATS:
            errors.append(
                ArtifactError(
                    code="unknown_format",
                    message=f"unknown export format {fmt!r}",
                    stage="export",
                    context={"format": fmt},
                )
            )
            continue

        source_name, ext = _EXPORT_SINGLE_FILE_FORMATS[fmt]
        source_path = resolved_output_dir / source_name
        if not source_path.is_file():
            errors.append(
                ArtifactError(
                    code="export_source_missing",
                    message=(
                        f"{source_path} does not exist -- build against this example_dir/backend "
                        f"first (printlab_check/_all for stl/step; printlab_all with a bambu/orca "
                        f"backend for 3mf)"
                    ),
                    stage="export",
                    context={"format": fmt},
                )
            )
            continue
        dest_path = dest / f"{prefix}.{ext}"
        shutil.copy2(source_path, dest_path)
        exported.append(ExportedFile(format=fmt, source=source_path, dest=dest_path))

    return ExportReport(
        status=Status.WARNING if errors else Status.OK,
        errors=errors,
        example_dir=Path(example_dir).resolve(),
        backend=backend,
        dest_dir=dest,
        name_prefix=prefix,
        exported=exported,
    )


def _numeric_delta(value_a, value_b) -> float | None:
    if isinstance(value_a, bool) or isinstance(value_b, bool):
        return None
    if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)):
        return float(value_b) - float(value_a)
    return None


def _resolve_printability_report_path(report_path: str) -> Path:
    path = Path(report_path)
    if path.is_dir():
        return path / pipeline.ARTIFACT_FILENAMES["printability_report"]
    return path


def printlab_diff(report_a: str, report_b: str) -> MetricsDiffReport:
    """Diff two printability_report.json runs: which `metrics{}` values
    changed (numerically, where both sides are numeric) and which `checks[]`
    entries changed status. `report_a`/`report_b` are each either a
    printability_report.json path directly, or a directory containing one
    (`<dir>/printability_report.json`). Makes AGENTS.md's "compare metrics
    numerically across runs" guidance mechanical instead of an eyeballed
    JSON diff."""
    path_a = _resolve_printability_report_path(report_a)
    path_b = _resolve_printability_report_path(report_b)
    report_a_model = pipeline.read_json_artifact(path_a, PrintabilityReport)
    report_b_model = pipeline.read_json_artifact(path_b, PrintabilityReport)

    metric_deltas: list[MetricDelta] = []
    all_metric_keys = sorted(set(report_a_model.metrics) | set(report_b_model.metrics))
    for key in all_metric_keys:
        value_a = report_a_model.metrics.get(key)
        value_b = report_b_model.metrics.get(key)
        if value_a == value_b:
            continue
        metric_deltas.append(
            MetricDelta(
                metric=key, value_a=value_a, value_b=value_b, delta=_numeric_delta(value_a, value_b)
            )
        )

    checks_a = {check.name: check.status for check in report_a_model.checks}
    checks_b = {check.name: check.status for check in report_b_model.checks}
    check_changes: list[CheckStatusChange] = []
    for name in sorted(set(checks_a) | set(checks_b)):
        status_a = checks_a.get(name)
        status_b = checks_b.get(name)
        if status_a != status_b:
            check_changes.append(CheckStatusChange(name=name, status_a=status_a, status_b=status_b))

    return MetricsDiffReport(
        report_a=str(path_a), report_b=str(path_b), metric_deltas=metric_deltas, check_changes=check_changes
    )


def printlab_doctor() -> dict:
    """Report installed vs. pinned native toolchain versions, per backend."""
    from printlab.slicing import available_backend_names, detect_all
    from printlab.toolchain import load_pinned_tools

    try:
        pinned = load_pinned_tools()
    except FileNotFoundError:
        pinned = {}

    capabilities = detect_all()
    backends = []
    for name in available_backend_names():
        cap = capabilities[name]
        pinned_version = pinned.get(_BACKEND_TOOL_KEY.get(name, name), {}).get("version")
        if not cap.available:
            status = "missing"
        elif pinned_version and cap.version != pinned_version:
            status = "warn"
        else:
            status = "ok"
        backends.append(
            {
                "backend": name,
                "status": status,
                "available": cap.available,
                "installed_version": cap.version,
                "pinned_version": pinned_version,
                "notes": cap.notes,
            }
        )
    return {
        "backends": backends,
        # The one piece of "hidden" global state every example_dir call
        # depends on: printlab.toml [profiles] paths resolve relative to
        # this, the server process's cwd at launch -- not example_dir's
        # location (see printlab.pipeline.load_part_config).
        "repo_root": str(Path.cwd().resolve()),
        "output_dir_note": (
            "output/<backend>/ under any example_dir is fully disposable: printlab_check/"
            "printlab_all wipe and regenerate it (clean=True) on every run against that "
            "backend. Never hand-edit anything under it."
        ),
    }


#: Canonical printlab.toml profile paths, matching every checked-in example
#: (see e.g. examples/bracket/printlab.toml) -- printlab_init's scaffold uses
#: these so a new example lands on the same printer/material/process as the
#: rest of the repo unless the caller edits the file afterward.
_DEFAULT_PROFILE_PATHS = {
    "printer": "profiles/printers/bambu_a1.yaml",
    "material": "profiles/materials/pla.yaml",
    "process": "profiles/processes/draft.yaml",
}

#: See printlab.pipeline.load_part_config's docstring for the same fact --
#: kept in sync there since that's the other place this exact caveat lives.
_PROFILE_PATH_COMMENT = (
    "# Paths are resolved relative to the printlab MCP server's working\n"
    "# directory at launch -- typically wherever printlab was installed via\n"
    "# `uv --directory <path>`, not this file's location. Run printlab_doctor\n"
    "# to confirm which backends that installation can see."
)


def printlab_init(example_dir: str, module: str = "part.py") -> str:
    """Scaffold a printlab.toml in example_dir, pointing at an existing CAD
    module (default part.py, but any filename works -- see printlab.toml's
    [part].module) with the default printer/material/process profiles.
    Refuses to overwrite an existing printlab.toml; use printlab_describe to
    inspect one first."""
    example_path = Path(example_dir)
    if not example_path.is_dir():
        raise pipeline.PipelineError(f"{example_path} is not a directory")
    config_path = example_path / "printlab.toml"
    if config_path.is_file():
        raise pipeline.PipelineError(
            f"{config_path} already exists; printlab_init refuses to overwrite it "
            "(use printlab_describe to inspect it instead)"
        )
    part_module_path = example_path / module
    if not part_module_path.is_file():
        raise pipeline.PipelineError(
            f"{part_module_path} does not exist -- printlab_init scaffolds a printlab.toml "
            "pointing at an existing CAD module, it does not create one"
        )

    contents = (
        f"# Example part configuration for `printlab build|mesh|slice|... {example_path}`.\n"
        f"{_PROFILE_PATH_COMMENT}\n"
        "\n"
        "[part]\n"
        f'name = "{example_path.name}"\n'
        f'module = "{module}"\n'
        'function = "build"\n'
        "\n"
        "[profiles]\n"
        f'printer = "{_DEFAULT_PROFILE_PATHS["printer"]}"\n'
        f'material = "{_DEFAULT_PROFILE_PATHS["material"]}"\n'
        f'process = "{_DEFAULT_PROFILE_PATHS["process"]}"\n'
    )
    config_path.write_text(contents)
    return str(config_path)


def printlab_describe(example_dir: str) -> dict:
    """Resolve example_dir's printlab.toml without building anything: which
    CAD module/function will run, the profile paths (and the repo_root
    they're resolved against), whether an [fea] load case is configured, and
    the output-directory layout/disposability contract."""
    config = pipeline.load_part_config(Path(example_dir))
    return {
        "name": config.name,
        "part_py": str(config.part_py),
        "build_function": config.build_function,
        "printer_profile_path": str(config.printer_profile_path),
        "material_profile_path": str(config.material_profile_path),
        "process_profile_path": str(config.process_profile_path),
        "fea_configured": config.fea_load_case is not None,
        "repo_root": str(Path.cwd().resolve()),
        "default_output_dir_pattern": str(config.example_dir / "output" / "<backend>"),
        "output_dir_note": (
            "output/<backend>/ is fully disposable: printlab_check/printlab_all wipe and "
            "regenerate it (clean=True) on every run against that backend. Never hand-edit "
            "anything under it -- only example_dir's CAD source (part_py above) is durable."
        ),
    }
