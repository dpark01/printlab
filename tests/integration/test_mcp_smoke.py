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


def test_fea_preview_returns_structured_result():
    """printlab_fea_preview needs no [fea] load case, unlike printlab_fea --
    works against bracket, which has none configured (issue #5.2)."""
    from tests.conftest import skip_unless_importable

    skip_unless_importable("gmsh")

    result = _call("printlab_fea_preview", {"example_dir": str(EXAMPLES_DIR / "bracket")})
    assert result.is_error is False
    assert result.structured_content["status"] in {"ok", "warning", "error"}
    if result.structured_content["status"] != "error":
        assert result.structured_content["mesh_node_count"] > 0
        assert result.structured_content["mesh_element_count"] > 0


def test_fea_preview_meshing_failure_is_a_clean_error_report_not_a_crash():
    """The whole point of issue #4/#5.2: a mesh sizing Gmsh can't handle must
    come back as a structured error, and the server must still be alive for
    the next call -- never a crashed process."""
    from tests.conftest import skip_unless_importable

    skip_unless_importable("gmsh")

    result = _call(
        "printlab_fea_preview",
        {"example_dir": str(EXAMPLES_DIR / "bracket"), "mesh_size_mm": -1.0},
    )
    assert result.is_error is False  # a meshing failure is a report, not a tool error
    assert result.structured_content["status"] == "error"
    assert result.structured_content["mesh_node_count"] is None

    # The server must still be responsive after the meshing failure above.
    doctor_result = _call("printlab_doctor", {})
    assert doctor_result.is_error is False


def test_probe_classifies_points():
    result = _call(
        "printlab_probe",
        {
            "example_dir": str(EXAMPLES_DIR / "bracket"),
            "points": [(0.0, 0.0, 0.0), (10000.0, 10000.0, 10000.0)],
        },
    )
    assert result.is_error is False
    classifications = [p["classification"] for p in result.structured_content["points"]]
    assert classifications[1] == "OUT"  # far outside any real part's bounding box
    assert classifications[0] in {"IN", "OUT", "ON"}


def test_export_copies_stl_and_step(tmp_path):
    # printlab_export never builds -- prime output/check/ first.
    check_result = _call("printlab_check", {"example_dir": str(EXAMPLES_DIR / "bracket")})
    assert check_result.is_error is False

    export_result = _call(
        "printlab_export",
        {
            "example_dir": str(EXAMPLES_DIR / "bracket"),
            "backend": "check",
            "dest_dir": str(tmp_path),
            "formats": ["stl", "step"],
            "name_prefix": "smoke_test_bracket",
        },
    )
    assert export_result.is_error is False
    assert export_result.structured_content["status"] == "ok"
    assert (tmp_path / "smoke_test_bracket.stl").is_file()
    assert (tmp_path / "smoke_test_bracket.step").is_file()


def test_diff_reports_metric_deltas_between_two_checks(tmp_path):
    output_a = tmp_path / "a"
    output_b = tmp_path / "b"
    result_a = _call(
        "printlab_check", {"example_dir": str(EXAMPLES_DIR / "bracket"), "output_dir": str(output_a)}
    )
    result_b = _call(
        "printlab_check", {"example_dir": str(EXAMPLES_DIR / "bracket"), "output_dir": str(output_b)}
    )
    assert result_a.is_error is False
    assert result_b.is_error is False

    diff_result = _call("printlab_diff", {"report_a": str(output_a), "report_b": str(output_b)})
    assert diff_result.is_error is False
    # Two independent runs of the same CAD source are deterministic (see
    # tests/integration/test_check_golden.py) -- nothing should have moved.
    assert diff_result.structured_content["metric_deltas"] == []
    assert diff_result.structured_content["check_changes"] == []


def test_render_rebuilt_reflects_function_switch(tmp_path):
    """Regression test for issue #5.1: printlab_render used to silently reuse
    a stale build (keyed only on part.stl's presence) after a `function`
    switch; `rebuilt` in the response must now say what actually happened."""
    (tmp_path / "part.py").write_text(
        "import cadquery as cq\n"
        "def build():\n"
        "    return cq.Workplane('XY').box(5, 5, 5)\n"
        "def build_alt():\n"
        "    return cq.Workplane('XY').box(9, 9, 9)\n"
    )
    init_result = _call("printlab_init", {"example_dir": str(tmp_path)})
    assert init_result.is_error is False

    first = _call("printlab_render", {"example_dir": str(tmp_path), "views": ["iso"]})
    assert first.is_error is False
    assert first.structured_content["rebuilt"] is True

    second = _call("printlab_render", {"example_dir": str(tmp_path), "views": ["iso"]})
    assert second.is_error is False
    assert second.structured_content["rebuilt"] is False  # nothing changed -- reuse the build

    switched = _call(
        "printlab_render", {"example_dir": str(tmp_path), "views": ["iso"], "function": "build_alt"}
    )
    assert switched.is_error is False
    assert switched.structured_content["rebuilt"] is True  # function switch forces a rebuild
