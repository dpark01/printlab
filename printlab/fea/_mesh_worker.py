"""Subprocess entry point for Gmsh meshing -- `python -m printlab.fea._mesh_worker`.

Isolated in its own child process, invoked by printlab.fea.mesh_runner, exactly
like printlab.fea.solve.run_ccx shells out to `ccx` and the slicer backends
shell out to their CLIs: a meshing failure here -- on whatever thread Gmsh
misbehaves on -- can only kill this child process, never the caller (e.g. the
MCP server, which dispatches sync tools off the main thread; see
printlab.fea.mesh's docstring for why Gmsh's default SIGINT handler already
can't be installed there).

Never imported directly by anything except as `python -m ...`; keeps
printlab.fea.mesh_runner importable (and printlab_mcp's tools without it)
without the `fea` extra installed.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import numpy as np


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step_path", type=Path)
    parser.add_argument("output_npz_path", type=Path)
    parser.add_argument("--mesh-size", dest="mesh_size_mm", type=float, default=None)
    args = parser.parse_args(argv)

    try:
        from printlab.fea.mesh import mesh_step

        nodes, elements, resolved_mesh_size_mm = mesh_step(
            args.step_path, mesh_size_mm=args.mesh_size_mm
        )
    except Exception:  # noqa: BLE001 - deliberately broad: any failure must
        # surface as a clean non-zero exit + stderr traceback, never a crash
        # the parent process can't recover from.
        traceback.print_exc()
        return 1

    args.output_npz_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        args.output_npz_path,
        nodes=nodes,
        elements=elements,
        resolved_mesh_size_mm=np.float64(resolved_mesh_size_mm),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
