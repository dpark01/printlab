"""STEP -> linear-tetrahedral mesh via Gmsh's OCC kernel.

Isolated in its own module because it needs the optional `gmsh` dependency
(the `fea` extra); printlab.fea.deck stays importable without it. Returns plain
numpy arrays -- nodes as an (N,3) contiguous coordinate array and elements as
(M,4) connectivity 0-indexed into that array -- so nothing downstream (deck
writing, node selection) needs Gmsh or its 1-indexed, non-contiguous tags.

Gmsh's Python API is a global-state C library: this module initializes it only
if the caller hasn't, and finalizes only what it started, so repeated calls
across a test session don't stomp on each other.
"""

from __future__ import annotations

from pathlib import Path

import gmsh
import numpy as np

#: Gmsh element type id for the 4-node linear tetrahedron (C3D4-compatible).
_GMSH_TET4 = 4


def mesh_step(
    step_path: Path, *, mesh_size_mm: float | None = None
) -> tuple[np.ndarray, np.ndarray, float]:
    """Mesh `step_path` into linear tets. Returns (nodes, elements, resolved_mesh_size_mm).

    `nodes` is (N,3) float mm; `elements` is (M,4) int, 0-indexed into `nodes`.
    If `mesh_size_mm` is None a characteristic size of ~1/20 of the bounding-box
    diagonal is used, a compromise between element count and solve time for a
    crude v1 analysis; `resolved_mesh_size_mm` echoes back whichever size (given
    or defaulted) was actually handed to Gmsh, so a caller passing `None` can
    still learn/report what ran.
    """
    step_path = Path(step_path)

    initialized_here = False
    if not gmsh.isInitialized():
        # interruptible=False: the default installs a SIGINT handler, which
        # Python only allows from the main thread of the main interpreter --
        # this call runs on a worker thread when invoked via the MCP server
        # (FastMCP dispatches sync tools off-thread), so the default raises
        # "signal only works in main thread of the main interpreter".
        gmsh.initialize(interruptible=False)
        initialized_here = True
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.clear()
        gmsh.model.add("printlab_fea")
        gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()

        if mesh_size_mm is None:
            xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
            diagonal = float(np.linalg.norm([xmax - xmin, ymax - ymin, zmax - zmin]))
            mesh_size_mm = diagonal / 20.0
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size_mm)
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0.0)
        # Order 1 == linear (4-node) tets; keep it explicit so an upstream
        # default change can't silently produce C3D10 the deck can't emit.
        gmsh.option.setNumber("Mesh.ElementOrder", 1)

        gmsh.model.mesh.generate(3)

        node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
        node_tags = np.asarray(node_tags, dtype=np.int64)
        nodes = np.asarray(node_coords, dtype=float).reshape(-1, 3)

        # Gmsh tags are 1-based and need not be contiguous; remap to dense
        # 0-based indices so the deck can emit id+1 without gaps.
        tag_to_index = np.full(node_tags.max() + 1, -1, dtype=np.int64)
        tag_to_index[node_tags] = np.arange(node_tags.size)

        elem_types, _, elem_node_tags = gmsh.model.mesh.getElements(dim=3)
        tet_conn: np.ndarray | None = None
        for elem_type, conn_tags in zip(elem_types, elem_node_tags, strict=True):
            if int(elem_type) == _GMSH_TET4:
                tet_conn = tag_to_index[np.asarray(conn_tags, dtype=np.int64).reshape(-1, 4)]
                break
        if tet_conn is None:
            raise RuntimeError(f"Gmsh produced no linear tetrahedra for {step_path}")

        return nodes, tet_conn.astype(np.int64), float(mesh_size_mm)
    finally:
        if initialized_here:
            gmsh.finalize()
