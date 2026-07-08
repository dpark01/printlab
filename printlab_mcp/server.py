"""FastMCP wrapper around printlab_mcp.tools -- the only module importing fastmcp.

Each tool delegates to a plain function in `tools.py` and translates PrintLab's
own failures (`pipeline.PipelineError`, `printlab.cad.PartBuildError`) into
`ToolError` so they come back to the client as clean `isError: true` results
instead of opaque tracebacks.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager

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
        "Deterministic 3D-printability analysis. The pipeline owns the truth; "
        "propose CAD-source edits from the returned artifacts, never by eyeballing. "
        "printlab_check needs no slicer; printlab_all requires an installed backend "
        "(query printlab_doctor first)."
    ),
)


@contextmanager
def _translate_errors():
    try:
        yield
    except (pipeline.PipelineError, PartBuildError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool
def printlab_check(example_dir: str) -> PrintabilityReport:
    """Run build -> mesh -> evaluate -> report with slicing skipped (no slicer needed)."""
    with _translate_errors():
        return tools.printlab_check(example_dir)


@mcp.tool
def printlab_all(example_dir: str, backend: str = "prusaslicer") -> PrintabilityReport:
    """Run the full pipeline: build -> mesh -> slice -> gcode -> evaluate -> report."""
    with _translate_errors():
        return tools.printlab_all(example_dir, backend)


@mcp.tool
def printlab_orient(example_dir: str, backend: str = "check") -> OrientationSearchReport:
    """Try axis-aligned rotations of part.stl and recommend one (mesh-metrics only)."""
    with _translate_errors():
        return tools.printlab_orient(example_dir, backend)


@mcp.tool
def printlab_render(
    example_dir: str, views: list[str] | None = None, backend: str = "check"
) -> ToolResult:
    """Render part.stl to PNG(s); returns the RenderReport plus the images inline."""
    with _translate_errors():
        report = tools.printlab_render(example_dir, views=views, backend=backend)
    images = [Image(path=view.output_path).to_image_content() for view in report.views]
    return ToolResult(content=images, structured_content=report.model_dump(mode="json"))


@mcp.tool
def printlab_fea(example_dir: str, backend: str = "check") -> FEAReport:
    """Run a linear-static FEA (CalculiX) using printlab.toml's [fea] load case.
    Requires the `fea` extra (gmsh) and `ccx` on PATH; a crude single-run
    analysis on placeholder material constants, not certification-grade."""
    with _translate_errors():
        return tools.printlab_fea(example_dir, backend)


@mcp.tool
def printlab_doctor() -> dict:
    """Report installed vs. pinned native slicer versions, per backend."""
    return tools.printlab_doctor()


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
