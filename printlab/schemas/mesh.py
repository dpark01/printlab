"""Mesh analysis artifact: printlab.mesh.analyze() -> mesh_report.json.

v0.1 covered geometry metrics only (manifold/watertight/self-intersections/
shells/bbox/surface area/volume). Overhang analysis (printlab.mesh.overhangs),
wall thickness estimation (printlab.mesh.wall_thickness), and unsupported
span detection (printlab.mesh.bridges) were added in Phase B as bounded,
documented approximations, not slicer-accurate simulations.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict, Field

from printlab.schemas.common import BBox, PrintLabArtifact


class MeshReport(PrintLabArtifact):
    model_config = ConfigDict(extra="forbid")

    input_path: Path
    input_sha256: str

    manifold: bool
    watertight: bool
    self_intersecting: bool
    self_intersection_count: int
    shell_count: int

    bbox: BBox
    surface_area_mm2: float
    volume_mm3: float

    # Overhang analysis -- see printlab.mesh.overhangs for the exact
    # convention and documented limitations (per-face-normal approximation,
    # not a slicer-accurate support simulation).
    build_direction: tuple[float, float, float] = (0.0, 0.0, 1.0)
    overhang_area_mm2: float = 0.0
    overhang_histogram: dict[str, float] = Field(default_factory=dict)

    min_wall_thickness_mm: float | None = Field(
        default=None,
        description=(
            "5th-percentile of per-face ray-cast thickness readings, not a "
            "strict minimum -- can overestimate true worst-case thickness "
            "near sharp edges (see printlab.mesh.wall_thickness for the "
            "worked example). None means ray casting produced no usable "
            "samples (e.g. a badly broken mesh), not 'no thin walls found.'"
        ),
    )
    min_wall_thickness_location: tuple[float, float, float] | None = Field(
        default=None,
        description=(
            "Centroid, in the part's native coordinate frame, of the face "
            "nearest the reported min_wall_thickness_mm percentile. None "
            "whenever min_wall_thickness_mm is None."
        ),
    )

    # Longest contiguous unsupported region's span -- see
    # printlab.mesh.bridges. None means there are no overhang regions at
    # all, not "unknown."
    max_unsupported_span_mm: float | None = None


class MeshRepairReport(PrintLabArtifact):
    """printlab.mesh.repair() -> mesh_repair_report.json.

    Only the cheap, well-understood fixes trimesh ships are attempted
    (degenerate-face removal, vertex merging, hole filling, normal/winding
    correction) -- this is not a general-purpose mesh-healing tool. If a
    mesh is still broken afterward, that's reported plainly rather than
    hidden; PrintLab does not claim to fix everything.
    """

    model_config = ConfigDict(extra="forbid")

    input_path: Path
    input_sha256: str
    output_path: Path | None = None

    repair_attempted: bool
    fixes_applied: list[str] = Field(default_factory=list)

    manifold_before: bool
    watertight_before: bool
    manifold_after: bool
    watertight_after: bool
