"""Heavy-lane smoke test for the FastMCP server.

Skips if fastmcp isn't installed (the same graceful-skip pattern slicer-
dependent tests use via backend.detect().available). Exercises FastMCP's
in-process client against examples/bracket -- a real CadQuery build, but no
slicer -- to confirm a tool returns structured content and that a bogus
example_dir comes back as a client-visible error rather than a traceback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

fastmcp = pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

from printlab_mcp.server import mcp  # noqa: E402

pytestmark = pytest.mark.integration

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def _call(name: str, arguments: dict, **kwargs):
    async def run():
        async with Client(mcp) as client:
            return await client.call_tool(name, arguments, **kwargs)

    return asyncio.run(run())


def test_check_returns_structured_status():
    result = _call("printlab_check", {"example_dir": str(EXAMPLES_DIR / "bracket")})
    assert result.is_error is False
    assert result.structured_content["status"] in {"ok", "warning", "error"}


def test_check_bogus_dir_is_error():
    result = _call(
        "printlab_check",
        {"example_dir": str(EXAMPLES_DIR / "does_not_exist")},
        raise_on_error=False,
    )
    assert result.is_error is True


def test_render_grid_layout_dedupes_images():
    result = _call(
        "printlab_render",
        {
            "example_dir": str(EXAMPLES_DIR / "bracket"),
            "views": ["top", "front", "right", "iso"],
            "layout": "grid",
        },
    )
    assert result.is_error is False
    assert result.structured_content["layout"] == "grid"
    assert len(result.structured_content["views"]) == 4
    # All 4 views share one composite output file -- exactly one image
    # should be attached, not four (see printlab_mcp.server's de-dupe logic).
    assert len(result.content) == 1


def test_render_focus_zoom_is_echoed():
    result = _call(
        "printlab_render",
        {
            "example_dir": str(EXAMPLES_DIR / "bracket"),
            "views": ["iso"],
            "focus_center": (0.0, 0.0, 0.0),
            "focus_radius": 5.0,
        },
    )
    assert result.is_error is False
    assert result.structured_content["focus_center"] == [0.0, 0.0, 0.0]
    assert result.structured_content["focus_radius"] == 5.0


def test_render_custom_elevation_azimuth():
    result = _call(
        "printlab_render",
        {"example_dir": str(EXAMPLES_DIR / "bracket"), "elevation": 15.0, "azimuth": 45.0},
    )
    assert result.is_error is False
    (view,) = result.structured_content["views"]
    assert (view["label"], view["elevation_deg"], view["azimuth_deg"]) == ("custom", 15.0, 45.0)


def test_init_then_describe_round_trip(tmp_path):
    (tmp_path / "part.py").write_text("def build():\n    ...\n")

    init_result = _call("printlab_init", {"example_dir": str(tmp_path)})
    assert init_result.is_error is False
    assert (tmp_path / "printlab.toml").is_file()

    describe_result = _call("printlab_describe", {"example_dir": str(tmp_path)})
    assert describe_result.is_error is False
    assert describe_result.structured_content["fea_configured"] is False
    assert describe_result.structured_content["part_py"] == str(tmp_path / "part.py")


def test_doctor_reports_repo_root():
    result = _call("printlab_doctor", {})
    assert result.is_error is False
    assert "repo_root" in result.structured_content


def test_fea_returns_structured_result():
    """Regression test: gmsh.initialize() installs a SIGINT handler by
    default, which only Python's main thread may do -- FastMCP dispatches
    sync tools off-thread, so this failed until mesh.py passed
    interruptible=False (see printlab.fea.mesh)."""
    from tests.conftest import skip_unless_importable

    skip_unless_importable("gmsh")
    from printlab.fea.solve import find_ccx_binary

    if find_ccx_binary() is None:
        pytest.skip("ccx binary not installed on this machine")

    result = _call("printlab_fea", {"example_dir": str(EXAMPLES_DIR / "hook")})
    assert result.is_error is False
    assert result.structured_content["status"] in {"ok", "warning", "error"}
    assert result.structured_content["max_displacement_mm"] > 0
