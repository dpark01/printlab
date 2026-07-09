"""FastMCP wrapper around printlab_mcp.tools -- the only module importing fastmcp.

Each tool delegates to a plain function in `tools.py` and translates PrintLab's
own failures (`pipeline.PipelineError`, `printlab.cad.PartBuildError`) into
`ToolError` so they come back to the client as clean `isError: true` results
instead of opaque tracebacks.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.tool import ToolResult
from fastmcp.utilities.types import Image

from printlab import pipeline
from printlab.cad import PartBuildError
from printlab.schemas import FEAReport, OrientationSearchReport, PrintabilityReport
from printlab_mcp import tools

mcp = FastMCP(
    "printlab",
    instructions=(
        "Deterministic 3D-printability analysis. The pipeline owns the truth; propose "
        "CAD-source edits from the returned artifacts, never by eyeballing. Read the "
        "structured `checks[]`/`metrics{}` fields, not prose messages. "
        "`provisional_score` is UNCALIBRATED (`score_calibrated` is false in v1) -- "
        "never optimize it; reason about `checks[]`/`metrics{}` instead. Always rerun "
        "after a CAD-source edit before drawing a conclusion, and compare metrics "
        "numerically across runs, not visually. `output/<backend>/` is fully "
        "disposable -- every run against a backend wipes and regenerates it; never "
        "hand-edit anything under it. printlab_check needs no slicer; printlab_all "
        "requires an installed backend (query printlab_doctor first). 'check' is a "
        "no-slicer sentinel accepted by `backend` parameters, not a real backend "
        "name. No printlab.toml in a target directory? Call printlab_init to "
        "scaffold one, or printlab_describe to inspect an existing one without "
        "building anything. Try printlab_orient before manually second-guessing a "
        "part's build orientation. Prefer a bounded iterate-then-recheck loop (edit "
        "CAD source -> printlab_check/printlab_all -> compare -> repeat until no "
        "ERROR-level check remains and the target metric stops improving) over an "
        "open-ended edit/rerun cycle."
    ),
)


@contextmanager
def _translate_errors():
    try:
        yield
    except (pipeline.PipelineError, PartBuildError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool
def printlab_check(example_dir: str, output_dir: str | None = None) -> PrintabilityReport:
    """Run build -> mesh -> evaluate -> report with slicing skipped (no slicer
    needed). Writes into `<example_dir>/output/check/` by default -- fully
    disposable, wiped and regenerated on every call; pass `output_dir` to
    redirect artifacts elsewhere (e.g. a scratch dir, when example_dir isn't
    inside a printlab-managed tree)."""
    with _translate_errors():
        return tools.printlab_check(example_dir, output_dir=output_dir)


@mcp.tool
def printlab_all(
    example_dir: str, backend: str = "prusaslicer", output_dir: str | None = None
) -> PrintabilityReport:
    """Run the full pipeline: build -> mesh -> slice -> gcode -> evaluate ->
    report. Requires an installed slicer for `backend` (query printlab_doctor
    first) -- 'check' is not valid here; use printlab_check instead. Writes
    into `<example_dir>/output/<backend>/` by default (disposable, wiped each
    run); pass `output_dir` to redirect artifacts elsewhere."""
    with _translate_errors():
        return tools.printlab_all(example_dir, backend, output_dir=output_dir)


@mcp.tool
def printlab_orient(
    example_dir: str, backend: str = "check", output_dir: str | None = None
) -> OrientationSearchReport:
    """Try the 6 axis-aligned rotations of part.stl and recommend one by an
    explicit tie-break chain -- minimize overhang area, then maximize wall
    thickness, then minimize unsupported span -- not a weighted score (the
    response's `selection_reason` states this run's specific numbers).
    Mesh-metrics only (no re-slicing candidates); not part of printlab_all.
    `backend` selects which existing build to read/build ('check' is a
    no-slicer sentinel, the default, not a real backend name); pass
    `output_dir` to redirect artifacts."""
    with _translate_errors():
        return tools.printlab_orient(example_dir, backend, output_dir=output_dir)


@mcp.tool
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
) -> ToolResult:
    """Render part.stl to PNG(s); returns the RenderReport plus the images
    inline. Auto-builds via ensure_built if part.stl doesn't exist yet -- no
    prior printlab_check call is required.

    `views`: preset camera angles -- iso (3/4 angled), front/back (look
    along Y, lengthwise side profile), left/right (look along X, end-on
    silhouettes -- NOT a side profile despite the name), top/bottom (look
    along Z). Defaults to iso/front/top (or top/front/right/iso when
    `layout="grid"`). Pass BOTH `elevation` and `azimuth` (degrees) to render
    one custom angle instead of presets; a lone one is ignored.

    `layout="grid"` composites up to 4 views into a single 2x2 PNG at double
    the per-panel resolution, instead of one file per view.

    `focus_center`=(x, y, z) + `focus_radius` (mm) zoom into a fixed cube
    around a point, in the part's native coordinate frame, instead of
    framing the whole mesh -- use this for a small feature on an otherwise
    large part, where the default full-mesh framing would render it as a
    few illegible pixels.

    `backend` selects which existing build to read/build from ('check' is a
    no-slicer sentinel, the default, not a real backend name); pass
    `output_dir` to redirect artifacts elsewhere."""
    with _translate_errors():
        report = tools.printlab_render(
            example_dir,
            views=views,
            backend=backend,
            elevation=elevation,
            azimuth=azimuth,
            layout=layout,
            focus_center=focus_center,
            focus_radius=focus_radius,
            output_dir=output_dir,
        )
    # layout="grid" returns one RenderedView per view but they all share the
    # same composite output_path -- de-dupe so the image isn't attached
    # once per view.
    seen_paths: set[str] = set()
    images = []
    for view in report.views:
        path_str = str(view.output_path)
        if path_str in seen_paths:
            continue
        seen_paths.add(path_str)
        images.append(Image(path=view.output_path).to_image_content())
    return ToolResult(content=images, structured_content=report.model_dump(mode="json"))


@mcp.tool
def printlab_fea(
    example_dir: str, backend: str = "check", output_dir: str | None = None
) -> FEAReport:
    """Run a linear-static FEA (CalculiX) using printlab.toml's [fea] load
    case. Requires the `fea` extra (gmsh) and `ccx` on PATH; a crude
    single-run analysis on placeholder material constants, not
    certification-grade. Requires the target's printlab.toml to have an
    [fea] table (`load_point_mm`, `load_force_n`, `load_region_radius_mm`,
    optional `fixed_region`) -- call printlab_describe first to check
    `fea_configured` and avoid a guaranteed-fail round trip; only
    examples/hook has one built in today. `backend` is a no-slicer sentinel
    by default ('check'); pass `output_dir` to redirect artifacts."""
    with _translate_errors():
        return tools.printlab_fea(example_dir, backend, output_dir=output_dir)


@mcp.tool
def printlab_doctor() -> dict:
    """Report installed vs. pinned native slicer versions per backend, plus
    the resolved `repo_root` (the server process's working directory at
    launch) that every `example_dir` call's printlab.toml [profiles] paths
    resolve against."""
    return tools.printlab_doctor()


@mcp.tool
def printlab_init(example_dir: str, module: str = "part.py") -> str:
    """Scaffold a printlab.toml in example_dir, pointing at an existing CAD
    module (default `part.py` -- but any filename works, since `module` is
    just a relative path) with default printer/material/process profiles.
    Refuses to overwrite an existing printlab.toml, and refuses to scaffold
    a module that doesn't exist yet -- write the CAD source first. Returns
    the written printlab.toml's path."""
    with _translate_errors():
        return tools.printlab_init(example_dir, module)


@mcp.tool
def printlab_describe(example_dir: str) -> dict:
    """Resolve example_dir's printlab.toml without building anything: the
    CAD module/function that will run, the profile paths (and the
    `repo_root` they resolve against), whether an [fea] load case is
    configured, and the output-directory disposability contract. Use this
    to confirm "this builds Canoe.py's build()" without reading the toml by
    hand, or to check `fea_configured` before calling printlab_fea."""
    with _translate_errors():
        return tools.printlab_describe(example_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="printlab-mcp", description="Serve PrintLab tools over MCP (stdio by default)."
    )
    parser.add_argument("--http", action="store_true", help="Serve over HTTP instead of stdio.")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (with --http).")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port (with --http).")
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
