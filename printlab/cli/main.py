"""PrintLab CLI: printlab build|mesh|repair|orient|render|fea|slice|gcode|
evaluate|report|check|all|doctor <example_dir>

Every subcommand operates against `<example_dir>/output/<backend>/`, the one
self-contained deterministic output-directory bundle for a (part, backend)
pair (see printlab.pipeline). Subcommands other than `all`/`check` read their
upstream artifacts back from that directory rather than recomputing them, so
each stage stays independently executable per SETUP.md's design principle.
`check` uses the pseudo-backend name "check" (`output/check/`) since it never
invokes a slicer -- see `printlab.pipeline.run_check`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import typer

from printlab import pipeline
from printlab.fea.solve import detect_ccx_version, find_ccx_binary
from printlab.rendering import DEFAULT_VIEWS, CameraView
from printlab.schemas import GCodeReport, MeshReport, PrintabilityReport, RunManifest, SliceResult
from printlab.slicing import available_backend_names, detect_all
from printlab.toolchain import load_pinned_tools

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="A deterministic engineering environment for 3D-printable mechanical design.",
)

_BackendOption = typer.Option("prusaslicer", "--backend", "-b", help="Slicer backend to use.")
_OutputOption = typer.Option(
    None, "--output", "-o", help="Output directory (default: <example_dir>/output/<backend>)."
)
_ViewOption = typer.Option(
    list(DEFAULT_VIEWS), "--view", help="Preset name(s): iso/front/back/left/right/top/bottom."
)
_ElevationOption = typer.Option(None, "--elevation", help="Custom camera elevation, degrees.")
_AzimuthOption = typer.Option(None, "--azimuth", help="Custom camera azimuth, degrees.")
_WidthOption = typer.Option(800, "--width")
_HeightOption = typer.Option(600, "--height")
_LayoutOption = typer.Option(
    "separate",
    "--layout",
    help="'separate' (default, one PNG per view) or 'grid' (composite up to 4 views into one 2x2 PNG).",
)
_FocusCenterOption = typer.Option(
    None,
    "--focus-center",
    help="Region-of-interest center X Y Z (part-native mm) to zoom into instead of framing the whole mesh.",
)
_FocusRadiusOption = typer.Option(
    None, "--focus-radius", help="Half-width, mm, of the --focus-center cube; requires --focus-center."
)
_FunctionOption = typer.Option(
    None,
    "--function",
    help="Override printlab.toml's [part].function for this call only, without editing the file.",
)
_MeshSizeOption = typer.Option(
    None,
    "--mesh-size",
    help="Override the default ~bbox-diagonal/20 characteristic element size (mm) for FEA meshing.",
)


def _resolve_output_dir(config: pipeline.PartConfig, backend: str, output: Path | None) -> Path:
    return Path(output) if output else pipeline.default_output_dir(config, backend)


def _apply_function_override(config: pipeline.PartConfig, function: str | None) -> pipeline.PartConfig:
    return config if function is None else replace(config, build_function=function)


def _ensure_built(config: pipeline.PartConfig, output_dir: Path) -> None:
    """Build into `output_dir` if `part.stl` isn't present yet, or the
    existing build is stale (edited CAD source, or `--function` selecting a
    different builder than what produced it) -- mirrors
    printlab_mcp.tools.ensure_built so `--function` on orient/render/fea has
    an effect without a separate explicit `printlab build` first."""
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    if not stl_path.is_file() or not pipeline.build_is_fresh(config, output_dir):
        pipeline.prepare_output_dir(output_dir, clean=False)
        pipeline.stage_build(config, output_dir)


@app.command()
def build(
    example_dir: Path,
    backend: str = _BackendOption,
    output: Path | None = _OutputOption,
    function: str | None = _FunctionOption,
) -> None:
    """Build CAD source -> part.step + part.stl."""
    config = _apply_function_override(pipeline.load_part_config(example_dir), function)
    output_dir = _resolve_output_dir(config, backend, output)
    pipeline.prepare_output_dir(output_dir, clean=False)
    step_path, stl_path = pipeline.stage_build(config, output_dir)
    typer.echo(f"wrote {step_path}")
    typer.echo(f"wrote {stl_path}")


@app.command()
def mesh(example_dir: Path, backend: str = _BackendOption, output: Path | None = _OutputOption) -> None:
    """Analyze part.stl -> mesh_report.json."""
    config = pipeline.load_part_config(example_dir)
    output_dir = _resolve_output_dir(config, backend, output)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    report = pipeline.stage_mesh(stl_path, output_dir)
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def repair(example_dir: Path, backend: str = _BackendOption, output: Path | None = _OutputOption) -> None:
    """Attempt cheap mesh repair on part.stl -> mesh_repair_report.json.

    Not part of `printlab all`: CadQuery-sourced STLs are already clean by
    construction. This is for STL input from a source PrintLab doesn't
    control the origin of.
    """
    config = pipeline.load_part_config(example_dir)
    output_dir = _resolve_output_dir(config, backend, output)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    report = pipeline.stage_repair(stl_path, output_dir)
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def orient(
    example_dir: Path,
    backend: str = _BackendOption,
    output: Path | None = _OutputOption,
    function: str | None = _FunctionOption,
) -> None:
    """Try axis-aligned rotations of part.stl -> orientation_search_report.json.

    Mesh-metrics-only ranking (no re-slicing candidates); not part of
    `printlab all`. See printlab.mesh.orientation for the tie-break chain
    used to pick a winner. Auto-builds if part.stl is missing or stale
    (edited CAD source, or a different `--function`); pass `--function` to
    check an alternate builder without editing printlab.toml.
    """
    config = _apply_function_override(pipeline.load_part_config(example_dir), function)
    output_dir = _resolve_output_dir(config, backend, output)
    _ensure_built(config, output_dir)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    report = pipeline.stage_orientation_search(stl_path, output_dir)
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def render(
    example_dir: Path,
    view: list[str] = _ViewOption,
    elevation: float | None = _ElevationOption,
    azimuth: float | None = _AzimuthOption,
    width: int = _WidthOption,
    height: int = _HeightOption,
    layout: str = _LayoutOption,
    focus_center: tuple[float, float, float] | None = _FocusCenterOption,
    focus_radius: float | None = _FocusRadiusOption,
    backend: str = _BackendOption,
    output: Path | None = _OutputOption,
    function: str | None = _FunctionOption,
) -> None:
    """Render part.stl to PNG(s) -> render_report.json + render_*.png.

    Renders the `--view` presets by default; pass both `--elevation` and
    `--azimuth` to render one custom angle instead. Presets:
    iso (3/4 angled), front/back (look along Y, lengthwise side profile),
    left/right (look along X, end-on silhouettes -- not a side profile),
    top/bottom (look along Z). `--layout grid` composites up to 4 views into
    one 2x2 PNG instead of one file per view, at double the per-panel
    resolution so tiling doesn't shrink detail. `--focus-center`/
    `--focus-radius` zoom into a fixed cube instead of framing the whole
    mesh -- useful for a small feature on an otherwise large part. Not part
    of `printlab all`. The PNGs are not hashed for reproducibility
    (matplotlib-version dependent, like `part.stl`); only
    `render_report.json`'s camera metadata is. Auto-builds if part.stl is
    missing or stale (edited CAD source, or a different `--function`) --
    `render_report.json`'s `rebuilt` field says whether this call did so.
    """
    config = _apply_function_override(pipeline.load_part_config(example_dir), function)
    output_dir = _resolve_output_dir(config, backend, output)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    rebuilt = not stl_path.is_file() or not pipeline.build_is_fresh(config, output_dir)
    _ensure_built(config, output_dir)
    views: list[str | CameraView]
    if elevation is not None and azimuth is not None:
        views = [CameraView("custom", elevation, azimuth)]
    else:
        views = list(view)
    report = pipeline.stage_render(
        stl_path,
        output_dir,
        views=views,
        width_px=width,
        height_px=height,
        layout=layout,
        focus_center=focus_center,
        focus_radius=focus_radius,
        rebuilt=rebuilt,
    )
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def fea(
    example_dir: Path,
    backend: str = _BackendOption,
    output: Path | None = _OutputOption,
    function: str | None = _FunctionOption,
    mesh_size: float | None = _MeshSizeOption,
) -> None:
    """Run a linear-static FEA (CalculiX) using printlab.toml's [fea] load
    case -> fea_report.json.

    Requires the `fea` extra (gmsh) and `ccx` on PATH -- see `printlab
    doctor`. Not part of `printlab all`; a crude single-run analysis on
    placeholder material constants (see printlab.schemas.profiles), not a
    certification-grade result. Meshing runs in an isolated subprocess, so a
    Gmsh-level meshing failure can only fail this command, never crash the
    caller. `--mesh-size` overrides the [fea] table's `mesh_size_mm` (or the
    default ~bbox-diagonal/20 heuristic) -- see `printlab fea-preview` to
    check meshability first. Auto-builds if part.step is missing or stale.
    """
    config = _apply_function_override(pipeline.load_part_config(example_dir), function)
    if config.fea_load_case is None:
        typer.echo(f"error: {example_dir} has no [fea] load case in printlab.toml", err=True)
        raise typer.Exit(code=1)
    load_case = config.fea_load_case if mesh_size is None else config.fea_load_case.model_copy(
        update={"mesh_size_mm": mesh_size}
    )
    output_dir = _resolve_output_dir(config, backend, output)
    _ensure_built(config, output_dir)
    step_path = output_dir / pipeline.ARTIFACT_FILENAMES["step"]
    _, material, _ = pipeline.load_profiles(config)
    try:
        report = pipeline.stage_fea(step_path, output_dir, load_case=load_case, material=material)
    except pipeline.PipelineError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(report.model_dump_json(indent=2))
    if report.status.value == "error":
        raise typer.Exit(code=1)


@app.command(name="fea-preview")
def fea_preview(
    example_dir: Path,
    backend: str = _BackendOption,
    output: Path | None = _OutputOption,
    function: str | None = _FunctionOption,
    mesh_size: float | None = _MeshSizeOption,
) -> None:
    """Mesh-only, `ccx`-free pre-flight ahead of `printlab fea` ->
    fea_mesh_preview.json.

    Reports whether `--mesh-size` (or the default heuristic) can mesh the
    part's geometry at all, without running a full FEA solve or requiring a
    [fea] load case in printlab.toml. Meshing runs in the same isolated
    subprocess as `printlab fea`, so a meshing failure comes back as a
    structured `status="error"` report, never a crash -- use this before
    `printlab fea` on a part combining a large overall footprint with fine
    local features.
    """
    config = _apply_function_override(pipeline.load_part_config(example_dir), function)
    output_dir = _resolve_output_dir(config, backend, output)
    _ensure_built(config, output_dir)
    step_path = output_dir / pipeline.ARTIFACT_FILENAMES["step"]
    report = pipeline.stage_fea_preview(step_path, output_dir, mesh_size_mm=mesh_size)
    typer.echo(report.model_dump_json(indent=2))
    if report.status.value == "error":
        raise typer.Exit(code=1)


@app.command(name="slice")
def slice_cmd(example_dir: Path, backend: str = _BackendOption, output: Path | None = _OutputOption) -> None:
    """Slice part.stl with the chosen backend -> slice_result.json + G-code."""
    config = pipeline.load_part_config(example_dir)
    output_dir = _resolve_output_dir(config, backend, output)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    printer, material, process = pipeline.load_profiles(config)
    result = pipeline.stage_slice(
        config, stl_path, output_dir, backend, printer=printer, material=material, process=process
    )
    typer.echo(result.model_dump_json(indent=2))
    if result.status.value == "error":
        raise typer.Exit(code=1)


@app.command()
def gcode(example_dir: Path, backend: str = _BackendOption, output: Path | None = _OutputOption) -> None:
    """Parse the sliced G-code -> gcode_report.json (the authoritative slicing metrics)."""
    config = pipeline.load_part_config(example_dir)
    output_dir = _resolve_output_dir(config, backend, output)
    slice_result = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["slice_result"], SliceResult
    )
    _, material, _ = pipeline.load_profiles(config)
    report = pipeline.stage_gcode(slice_result, output_dir, material=material)
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def evaluate(example_dir: Path, backend: str = _BackendOption, output: Path | None = _OutputOption) -> None:
    """Combine mesh + G-code + printer constraints -> printability_report.json."""
    config = pipeline.load_part_config(example_dir)
    output_dir = _resolve_output_dir(config, backend, output)
    mesh_report = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["mesh_report"], MeshReport
    )
    gcode_report = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["gcode_report"], GCodeReport
    )
    printer, _, _ = pipeline.load_profiles(config)
    report = pipeline.stage_evaluate(mesh_report, gcode_report, output_dir, printer=printer)
    typer.echo(report.model_dump_json(indent=2))
    if report.status.value == "error":
        raise typer.Exit(code=1)


@app.command()
def report(example_dir: Path, backend: str = _BackendOption, output: Path | None = _OutputOption) -> None:
    """Render report.md from the artifacts already present in the output directory."""
    config = pipeline.load_part_config(example_dir)
    output_dir = _resolve_output_dir(config, backend, output)
    mesh_report = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["mesh_report"], MeshReport
    )
    slice_result = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["slice_result"], SliceResult
    )
    gcode_report = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["gcode_report"], GCodeReport
    )
    printability = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["printability_report"], PrintabilityReport
    )
    manifest = pipeline.read_json_artifact(
        output_dir / pipeline.ARTIFACT_FILENAMES["run_manifest"], RunManifest
    )
    report_path = pipeline.stage_report(
        config, mesh_report, slice_result, gcode_report, printability, manifest, output_dir
    )
    typer.echo(f"wrote {report_path}")
    typer.echo(f"wrote {output_dir / pipeline.ARTIFACT_FILENAMES['report_html']}")


@app.command()
def check(
    example_dir: Path, output: Path | None = _OutputOption, function: str | None = _FunctionOption
) -> None:
    """Run build -> mesh -> evaluate -> report with slicing skipped entirely.

    No slicer required: mesh-derived printability checks (manifold,
    build-volume fit, wall thickness) still run; slicer-derived metrics
    (filament mass, print time, layer count) come back null. Writes to
    `output/check/` by default, not a backend-named directory. See
    `printlab all` for the full-fidelity pipeline once a slicer is installed.
    `--function` overrides printlab.toml's `[part].function` for this call
    only, without editing the file.
    """
    try:
        result = pipeline.run_check(example_dir, output_dir=output, build_function=function)
    except pipeline.PipelineError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"output directory: {result['output_dir']}")
    typer.echo(f"printability status: {result['printability'].status.value}")
    typer.echo(f"report: {result['report_path']}")
    if result["printability"].status.value == "error":
        raise typer.Exit(code=1)


@app.command(name="all")
def run_all_cmd(
    example_dir: Path,
    backend: str = _BackendOption,
    output: Path | None = _OutputOption,
    function: str | None = _FunctionOption,
) -> None:
    """Run the full pipeline: build -> mesh -> slice -> gcode -> evaluate -> report.

    `--function` overrides printlab.toml's `[part].function` for this call
    only, without editing the file.
    """
    try:
        result = pipeline.run_all(example_dir, backend, output_dir=output, build_function=function)
    except pipeline.PipelineError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"output directory: {result['output_dir']}")
    typer.echo(f"printability status: {result['printability'].status.value}")
    typer.echo(f"report: {result['report_path']}")
    if result["printability"].status.value == "error":
        raise typer.Exit(code=1)


#: Maps a slicing backend's short name to its key in tools.toml (they differ
#: for bambu since the backend is named after the product line, "bambu",
#: while the pinned tool is the specific application, "bambustudio").
_BACKEND_TOOL_KEY = {"prusaslicer": "prusaslicer", "bambu": "bambustudio"}


@app.command()
def doctor() -> None:
    """Compare installed native toolchain versions against tools.toml's pins.

    A clean `doctor` run does not by itself guarantee Tier-1 reproducibility
    across machines -- what matters is that the *actual* resolved version
    recorded in each run's run_manifest.json matches. This command is a
    fast pre-flight check, not the reproducibility contract itself.
    """
    try:
        pinned = load_pinned_tools()
    except FileNotFoundError as exc:
        typer.echo(f"warning: {exc}", err=True)
        pinned = {}

    capabilities = detect_all()
    for name in available_backend_names():
        cap = capabilities[name]
        pin = pinned.get(_BACKEND_TOOL_KEY.get(name, name), {})
        pinned_version = pin.get("version")

        if not cap.available:
            typer.echo(f"[MISSING] {name}: not installed (pinned version: {pinned_version or 'n/a'})")
        elif pinned_version and cap.version != pinned_version:
            typer.echo(f"[WARN]    {name}: installed={cap.version}, pinned={pinned_version}")
        else:
            typer.echo(f"[OK]      {name}: {cap.version or 'unknown'}")
        if cap.notes:
            typer.echo(f"          {cap.notes}")

    # Not a slicing backend (no interchangeable alternatives), so it doesn't
    # go through the SlicerBackend/Capabilities abstraction -- same
    # [OK]/[WARN]/[MISSING] shape as the slicers above, checked directly.
    ccx_binary = find_ccx_binary()
    ccx_pinned_version = pinned.get("calculix", {}).get("version")
    if ccx_binary is None:
        typer.echo(f"[MISSING] calculix: not installed (pinned version: {ccx_pinned_version or 'n/a'})")
    else:
        ccx_version = detect_ccx_version(ccx_binary)
        if ccx_pinned_version and ccx_version != ccx_pinned_version:
            typer.echo(f"[WARN]    calculix: installed={ccx_version}, pinned={ccx_pinned_version}")
        else:
            typer.echo(f"[OK]      calculix: {ccx_version or 'unknown'}")


if __name__ == "__main__":
    app()
