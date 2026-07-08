"""FEA artifact schemas (v1): printlab.fea.analyze() -> FEAReport.

A deliberately small linear-static story: mesh the part, fix it where it sits
on the bed (bed adhesion is the real-world boundary condition for a printed
part), apply one point load, and report peak displacement + peak von Mises
stress with a rough safety factor. This is NOT a converged, certification-grade
model -- it's a crude single-run linear tet analysis on top of PLACEHOLDER
(uncalibrated) material constants (see printlab.schemas.profiles.MaterialProfile
and PrintabilityReport.provisional_score for the same "explicitly flagged
placeholder" framing). Treat the numbers as order-of-magnitude.

Standalone-importable on purpose (no import of printlab.fea's heavy gmsh/ccx
code): a consumer can construct/validate these models with zero native tools
installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from printlab.schemas.common import PrintLabArtifact


class FEALoadCase(BaseModel):
    """One static load case: where the part is held, and one applied force.

    `fixed_region` defaults to "bed_contact" -- the nodes resting on the print
    bed are fully constrained, matching how a printed part is physically held
    by bed adhesion at its base. The alternative (an explicit min/max box in mm)
    is an override path for a future non-bed-fixed case; v1's real usage is
    always the default.

    The load is a single force vector (`load_force_n`, in newtons) applied at
    `load_point_mm`. To avoid a stress singularity at one node, printlab.fea
    distributes it evenly over every mesh node within `load_region_radius_mm`
    of that point (falling back to the single nearest node if none are in
    range).
    """

    model_config = ConfigDict(extra="forbid")

    fixed_region: (
        Literal["bed_contact"] | tuple[tuple[float, float, float], tuple[float, float, float]]
    ) = "bed_contact"
    load_point_mm: tuple[float, float, float]
    load_force_n: tuple[float, float, float]
    load_region_radius_mm: float = 2.0


class FEAReport(PrintLabArtifact):
    """printlab.fea.analyze() -> fea_report.json.

    `safety_factor` is min(tensile_strength_xy, tensile_strength_z) /
    max_von_mises_stress -- a deliberately conservative, isotropic-strength
    stand-in, NOT a real anisotropic failure criterion. `None` when it cannot
    be computed (e.g. zero peak stress). `build_direction` records which axis
    was treated as the weak/interlayer direction for material orientation.
    """

    model_config = ConfigDict(extra="forbid")

    input_path: Path
    input_sha256: str
    solver: str = "calculix"
    solver_version: str | None = None
    load_case: FEALoadCase
    build_direction: tuple[float, float, float]
    mesh_node_count: int
    mesh_element_count: int
    max_displacement_mm: float
    max_von_mises_stress_mpa: float
    safety_factor: float | None = None
