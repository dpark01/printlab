"""Parent-side subprocess isolation for Gmsh meshing.

Mirrors printlab.fea.solve.run_ccx's and printlab.slicing.base's conventions:
shell out via `subprocess.run(..., timeout=...)`, list-form args, no shell,
`check=False` so the caller inspects the result itself. Deliberately does NOT
import `gmsh` (nor printlab.fea.mesh, which does) -- this module, and
everything that imports it, must stay importable without the `fea` extra so a
missing-`gmsh` failure is a clean `ModuleNotFoundError` raised here, not an
ImportError at module load time.

The actual meshing happens in a child process (`printlab.fea._mesh_worker`),
not in-process: a Gmsh-level failure on the FastMCP worker thread that hosts
`printlab_fea` was observed to kill the whole MCP server (see
printlab.fea.mesh's docstring on `interruptible=False` and issue #4) --
isolating it in a subprocess means a bad mesh can only kill that child.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

#: Default wall-clock budget for one meshing attempt -- generous relative to
#: printlab.fea.solve.run_ccx's 600s default since meshing a printable-sized
#: part is normally seconds, not minutes; a hang here (e.g. a degenerate
#: geometry Gmsh spins on) should still be bounded.
DEFAULT_MESH_TIMEOUT_S = 300.0

_MISSING_GMSH_MESSAGE = (
    "the `gmsh` package is not installed -- FEA meshing requires the `fea` "
    "extra (`uv sync --extra fea`)"
)


def run_mesh_worker(
    step_path: Path, *, mesh_size_mm: float | None = None, timeout: float = DEFAULT_MESH_TIMEOUT_S
) -> tuple[np.ndarray, np.ndarray, float]:
    """Mesh `step_path` in an isolated child process. Returns (nodes, elements,
    resolved_mesh_size_mm) -- see printlab.fea.mesh.mesh_step for the shape.

    Raises `ModuleNotFoundError` if `gmsh` isn't installed (checked here,
    before spawning a child, so the error matches what an in-process import
    would have raised) and `RuntimeError` if the child process fails (a real
    meshing error, e.g. incompatible mesh sizing against fine local features)
    or a bad/missing result -- the child's stderr tail is included so the
    underlying Gmsh error is still visible to the caller.
    """
    if importlib.util.find_spec("gmsh") is None:
        raise ModuleNotFoundError(_MISSING_GMSH_MESSAGE)

    step_path = Path(step_path)
    with tempfile.TemporaryDirectory(prefix="printlab_mesh_") as scratch:
        output_npz_path = Path(scratch) / "mesh.npz"
        args = [sys.executable, "-m", "printlab.fea._mesh_worker", str(step_path), str(output_npz_path)]
        if mesh_size_mm is not None:
            args += ["--mesh-size", str(mesh_size_mm)]

        try:
            completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Gmsh meshing of {step_path} timed out after {timeout}s (mesh_size_mm={mesh_size_mm})"
            ) from exc

        if completed.returncode != 0 or not output_npz_path.is_file():
            tail = (completed.stderr or "")[-2000:]
            raise RuntimeError(
                f"Gmsh meshing failed (exit {completed.returncode}); no usable mesh. "
                f"Last output:\n{tail}"
            )

        with np.load(output_npz_path) as data:
            nodes = data["nodes"]
            elements = data["elements"]
            resolved_mesh_size_mm = float(data["resolved_mesh_size_mm"])

    return nodes, elements, resolved_mesh_size_mm
