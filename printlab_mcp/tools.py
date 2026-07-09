"""PrintLab capabilities as plain functions, importing only `printlab`.

Kept free of any `fastmcp` import so it is unit-testable without the optional
MCP dependency installed; `server.py` wraps these and owns the MCP-specific
error translation. Failures propagate as `pipeline.PipelineError` (or
`printlab.cad.PartBuildError`) rather than being swallowed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from printlab import pipeline
from printlab.rendering import DEFAULT_VIEWS, CameraView
from printlab.schemas import FEAReport, OrientationSearchReport, PrintabilityReport, RenderReport

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
    example_dir: Path, backend: str, *, output_dir: Path | str | None = None
) -> tuple[pipeline.PartConfig, Path]:
    """Build if part.stl isn't present yet; return the resolved PartConfig and
    the output_dir actually used (either `output_dir` if given, else
    printlab.toml's default `<example_dir>/output/<backend>/`)."""
    config = pipeline.load_part_config(Path(example_dir))
    resolved_output_dir = Path(output_dir) if output_dir else pipeline.default_output_dir(config, backend)
    stl_path = resolved_output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    if not stl_path.is_file():
        pipeline.prepare_output_dir(resolved_output_dir, clean=False)
        pipeline.stage_build(config, resolved_output_dir)
    return config, resolved_output_dir


def printlab_check(example_dir: str, output_dir: str | None = None) -> PrintabilityReport:
    """Run build -> mesh -> evaluate -> report with slicing skipped."""
    return pipeline.run_check(Path(example_dir), output_dir=Path(output_dir) if output_dir else None)[
        "printability"
    ]


def printlab_all(
    example_dir: str, backend: str = "prusaslicer", output_dir: str | None = None
) -> PrintabilityReport:
    """Run the full pipeline: build -> mesh -> slice -> gcode -> evaluate -> report."""
    return pipeline.run_all(
        Path(example_dir), backend, output_dir=Path(output_dir) if output_dir else None
    )["printability"]


def printlab_orient(
    example_dir: str, backend: str = "check", output_dir: str | None = None
) -> OrientationSearchReport:
    """Try axis-aligned rotations of part.stl and recommend one."""
    _config, resolved_output_dir = ensure_built(Path(example_dir), backend, output_dir=output_dir)
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
) -> RenderReport:
    """Render part.stl to PNG(s) from named camera views."""
    _config, resolved_output_dir = ensure_built(Path(example_dir), backend, output_dir=output_dir)
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
    )


def printlab_fea(
    example_dir: str, backend: str = "check", output_dir: str | None = None
) -> FEAReport:
    """Run a linear-static FEA (CalculiX) using printlab.toml's [fea] load
    case. Requires the `fea` extra (gmsh) and `ccx` on PATH."""
    config, resolved_output_dir = ensure_built(Path(example_dir), backend, output_dir=output_dir)
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
