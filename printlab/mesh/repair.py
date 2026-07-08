"""Mesh repair: cheap, well-understood fixes only.

This is not a general-purpose mesh-healing tool -- it applies trimesh's own
repair primitives (degenerate-face removal, vertex merging, hole filling via
`trimesh.repair.fill_holes`, normal/winding correction) in a fixed order and
reports honestly whether the result is actually manifold/watertight
afterward. Meshes exported from a clean BREP kernel (CadQuery) essentially
never need this; it exists for meshes that arrive already broken (e.g. from
a source PrintLab doesn't control).
"""

from __future__ import annotations

from pathlib import Path

import trimesh

from printlab.determinism import hash_file
from printlab.schemas import ArtifactError, MeshRepairReport, Status


def repair(stl_path: Path, output_path: Path | None = None) -> MeshRepairReport:
    """Attempt to repair `stl_path`, optionally writing the result to `output_path`.

    Never raises: load failures are reported as a Status.ERROR
    MeshRepairReport with a structured ArtifactError, matching
    printlab.mesh.analyze's contract.
    """
    stl_path = Path(stl_path)

    try:
        input_sha256 = hash_file(stl_path)
        mesh = trimesh.load(stl_path, force="mesh")
    except Exception as exc:  # noqa: BLE001 - converted to a structured artifact error
        return MeshRepairReport(
            input_path=stl_path,
            input_sha256="",
            repair_attempted=False,
            manifold_before=False,
            watertight_before=False,
            manifold_after=False,
            watertight_after=False,
            status=Status.ERROR,
            errors=[
                ArtifactError(
                    code="mesh_load_failed",
                    message=str(exc),
                    stage="mesh_repair",
                    context={"input_path": str(stl_path)},
                )
            ],
        )

    watertight_before = bool(mesh.is_watertight)
    manifold_before = bool(mesh.is_watertight and mesh.is_winding_consistent)

    if manifold_before:
        return MeshRepairReport(
            input_path=stl_path,
            input_sha256=input_sha256,
            repair_attempted=False,
            manifold_before=True,
            watertight_before=True,
            manifold_after=True,
            watertight_after=True,
            status=Status.OK,
        )

    fixes_applied: list[str] = []

    nondegenerate_mask = mesh.nondegenerate_faces()
    if not nondegenerate_mask.all():
        mesh.update_faces(nondegenerate_mask)
        fixes_applied.append("removed_degenerate_faces")

    vertex_count_before = len(mesh.vertices)
    mesh.merge_vertices()
    if len(mesh.vertices) != vertex_count_before:
        fixes_applied.append("merged_duplicate_vertices")

    if not mesh.is_watertight:
        if trimesh.repair.fill_holes(mesh):
            fixes_applied.append("filled_holes")

    if not mesh.is_winding_consistent:
        trimesh.repair.fix_normals(mesh)
        fixes_applied.append("fixed_normals_winding")

    watertight_after = bool(mesh.is_watertight)
    manifold_after = bool(mesh.is_watertight and mesh.is_winding_consistent)

    output_written = None
    if fixes_applied and output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(output_path)
        output_written = output_path

    status = Status.OK
    errors: list[ArtifactError] = []
    if not manifold_after:
        status = Status.WARNING
        errors.append(
            ArtifactError(
                code="repair_incomplete",
                message="Mesh is still not manifold/watertight after the available repair "
                "steps; this is not a general-purpose mesh-healing tool.",
                stage="mesh_repair",
                context={"fixes_applied": fixes_applied},
            )
        )

    return MeshRepairReport(
        input_path=stl_path,
        input_sha256=input_sha256,
        output_path=output_written,
        repair_attempted=True,
        fixes_applied=fixes_applied,
        manifold_before=manifold_before,
        watertight_before=watertight_before,
        manifold_after=manifold_after,
        watertight_after=watertight_after,
        status=status,
        errors=errors,
    )
