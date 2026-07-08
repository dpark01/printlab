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


def test_fea_returns_structured_result():
    """Regression test: gmsh.initialize() installs a SIGINT handler by
    default, which only Python's main thread may do -- FastMCP dispatches
    sync tools off-thread, so this failed until mesh.py passed
    interruptible=False (see printlab.fea.mesh)."""
    pytest.importorskip("gmsh")
    from printlab.fea.solve import find_ccx_binary

    if find_ccx_binary() is None:
        pytest.skip("ccx binary not installed on this machine")

    result = _call("printlab_fea", {"example_dir": str(EXAMPLES_DIR / "hook")})
    assert result.is_error is False
    assert result.structured_content["status"] in {"ok", "warning", "error"}
    assert result.structured_content["max_displacement_mm"] > 0
