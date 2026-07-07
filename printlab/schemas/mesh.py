"""Mesh analysis artifact: printlab.mesh.analyze() -> mesh_report.json.

v0.1 covers geometry metrics only (manifold/watertight/self-intersections/
shells/bbox/surface area/volume). Manufacturing-tractability metrics that need
real geometry research (min wall thickness, overhangs, bridges) are deferred
to Phase 2 and live on PrintabilityReport once implemented, not here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict

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
