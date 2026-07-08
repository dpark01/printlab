"""Mesh analysis: printlab.mesh.analyze() -> MeshReport.

Geometry metrics only (manifold/watertight/shells/bbox/surface area/volume/
overhangs/wall thickness/unsupported spans). Overhang analysis (see
printlab.mesh.overhangs), wall thickness (see printlab.mesh.wall_thickness),
and unsupported span detection (see printlab.mesh.bridges) are bounded,
documented approximations -- not slicer-accurate simulations.

Self-intersection detection is likewise a hard problem in general (exact
triangle-pair testing needs a real boolean engine). v0.1 implements a
deliberately honest, bounded heuristic: it flags shells whose bounding boxes
overlap (the common failure mode of an accidentally duplicated/overlapping
body), and does not claim to catch every possible self-intersecting mesh.
"""

from __future__ import annotations

from pathlib import Path

import trimesh

from printlab.determinism import hash_file
from printlab.mesh.bridges import estimate_max_unsupported_span_mm
from printlab.mesh.overhangs import DEFAULT_BUILD_DIRECTION, compute_overhangs
from printlab.mesh.wall_thickness import estimate_min_wall_thickness_mm
from printlab.schemas import ArtifactError, BBox, MeshReport, Status


def _bounds_overlap(a: tuple, b: tuple) -> bool:
    (amin, amax), (bmin, bmax) = a, b
    return all(amin[i] <= bmax[i] and bmin[i] <= amax[i] for i in range(3))


def _shell_bbox_overlap_count(shells: list[trimesh.Trimesh]) -> int:
    """Best-effort inter-shell overlap count via bounding-box intersection.

    Exhaustive triangle-pair self-intersection testing is deferred to Phase 2
    — this only flags shells whose bounding boxes overlap, a cheap, honest
    proxy for the common failure mode, not a claim of exhaustive coverage.
    """
    count = 0
    boxes = [tuple(map(tuple, shell.bounds)) for shell in shells]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _bounds_overlap(boxes[i], boxes[j]):
                count += 1
    return count


def analyze(
    stl_path: Path, build_direction: tuple[float, float, float] = DEFAULT_BUILD_DIRECTION
) -> MeshReport:
    """Load an STL and compute geometry metrics. Never raises: load failures
    are reported as a Status.ERROR MeshReport with a structured ArtifactError,
    so a pipeline caller can branch on `.status` instead of catching exceptions.

    `build_direction` assumes the part is analyzed in its as-designed
    orientation (+Z) unless told otherwise -- see printlab.mesh.overhangs and
    the (deferred) orientation-search work for varying this.
    """
    stl_path = Path(stl_path)

    try:
        input_sha256 = hash_file(stl_path)
        loaded = trimesh.load(stl_path, force="mesh")
    except Exception as exc:  # noqa: BLE001 - converted to a structured artifact error
        return MeshReport(
            input_path=stl_path,
            input_sha256="",
            manifold=False,
            watertight=False,
            self_intersecting=False,
            self_intersection_count=0,
            shell_count=0,
            bbox=BBox(min=(0.0, 0.0, 0.0), max=(0.0, 0.0, 0.0)),
            surface_area_mm2=0.0,
            volume_mm3=0.0,
            status=Status.ERROR,
            errors=[
                ArtifactError(
                    code="mesh_load_failed",
                    message=str(exc),
                    stage="mesh",
                    context={"input_path": str(stl_path)},
                )
            ],
        )

    mesh: trimesh.Trimesh = loaded
    watertight = bool(mesh.is_watertight)
    manifold = bool(mesh.is_watertight and mesh.is_winding_consistent)

    shells = mesh.split(only_watertight=False)
    shell_count = max(len(shells), 1)
    overlap_count = _shell_bbox_overlap_count(list(shells)) if shell_count > 1 else 0

    bounds = mesh.bounds  # shape (2, 3): [min, max]
    bbox = BBox(min=tuple(float(v) for v in bounds[0]), max=tuple(float(v) for v in bounds[1]))

    overhang_histogram, overhang_area_mm2 = compute_overhangs(mesh, build_direction=build_direction)
    min_wall_thickness_mm = estimate_min_wall_thickness_mm(mesh)
    max_unsupported_span_mm = estimate_max_unsupported_span_mm(mesh, build_direction=build_direction)

    status = Status.OK
    errors: list[ArtifactError] = []
    if not watertight or not manifold:
        status = Status.WARNING
        errors.append(
            ArtifactError(
                code="mesh_not_manifold",
                message="Mesh is not watertight/manifold; downstream slicing metrics may be unreliable.",
                stage="mesh",
                context={"watertight": watertight, "manifold": manifold},
            )
        )

    return MeshReport(
        input_path=stl_path,
        input_sha256=input_sha256,
        manifold=manifold,
        watertight=watertight,
        self_intersecting=overlap_count > 0,
        self_intersection_count=overlap_count,
        shell_count=shell_count,
        bbox=bbox,
        surface_area_mm2=float(mesh.area),
        volume_mm3=float(mesh.volume),
        build_direction=build_direction,
        overhang_area_mm2=overhang_area_mm2,
        overhang_histogram=overhang_histogram,
        min_wall_thickness_mm=min_wall_thickness_mm,
        max_unsupported_span_mm=max_unsupported_span_mm,
        status=status,
        errors=errors,
    )
