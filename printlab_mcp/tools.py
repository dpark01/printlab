"""PrintLab capabilities as plain functions, importing only `printlab`.

Kept free of any `fastmcp` import so it is unit-testable without the optional
MCP dependency installed; `server.py` wraps these and owns the MCP-specific
error translation. Failures propagate as `pipeline.PipelineError` (or
`printlab.cad.PartBuildError`) rather than being swallowed here.
"""

from __future__ import annotations

from pathlib import Path

from printlab import pipeline
from printlab.rendering import DEFAULT_VIEWS
from printlab.schemas import FEAReport, OrientationSearchReport, PrintabilityReport, RenderReport

#: Mirrors printlab.cli.main._BACKEND_TOOL_KEY: a backend's short name differs
#: from its tools.toml key for bambu (backend "bambu" vs pinned "bambustudio").
_BACKEND_TOOL_KEY = {"prusaslicer": "prusaslicer", "bambu": "bambustudio"}


def ensure_built(example_dir: Path, backend: str) -> pipeline.PartConfig:
    """Build if part.stl isn't present yet; return the resolved PartConfig."""
    config = pipeline.load_part_config(Path(example_dir))
    output_dir = pipeline.default_output_dir(config, backend)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    if not stl_path.is_file():
        pipeline.prepare_output_dir(output_dir, clean=False)
        pipeline.stage_build(config, output_dir)
    return config


def printlab_check(example_dir: str) -> PrintabilityReport:
    """Run build -> mesh -> evaluate -> report with slicing skipped."""
    return pipeline.run_check(Path(example_dir))["printability"]


def printlab_all(example_dir: str, backend: str = "prusaslicer") -> PrintabilityReport:
    """Run the full pipeline: build -> mesh -> slice -> gcode -> evaluate -> report."""
    return pipeline.run_all(Path(example_dir), backend)["printability"]


def printlab_orient(example_dir: str, backend: str = "check") -> OrientationSearchReport:
    """Try axis-aligned rotations of part.stl and recommend one."""
    config = ensure_built(Path(example_dir), backend)
    output_dir = pipeline.default_output_dir(config, backend)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    return pipeline.stage_orientation_search(stl_path, output_dir)


def printlab_render(
    example_dir: str, views: list[str] | None = None, backend: str = "check"
) -> RenderReport:
    """Render part.stl to PNG(s) from named camera views."""
    config = ensure_built(Path(example_dir), backend)
    output_dir = pipeline.default_output_dir(config, backend)
    stl_path = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
    return pipeline.stage_render(stl_path, output_dir, views=views or list(DEFAULT_VIEWS))


def printlab_fea(example_dir: str, backend: str = "check") -> FEAReport:
    """Run a linear-static FEA (CalculiX) using printlab.toml's [fea] load
    case. Requires the `fea` extra (gmsh) and `ccx` on PATH."""
    config = ensure_built(Path(example_dir), backend)
    if config.fea_load_case is None:
        raise pipeline.PipelineError(f"{example_dir} has no [fea] load case in printlab.toml")
    output_dir = pipeline.default_output_dir(config, backend)
    step_path = output_dir / pipeline.ARTIFACT_FILENAMES["step"]
    _, material, _ = pipeline.load_profiles(config)
    return pipeline.stage_fea(step_path, output_dir, load_case=config.fea_load_case, material=material)


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
    return {"backends": backends}
