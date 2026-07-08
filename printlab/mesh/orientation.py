"""Orientation search (B.9): try several axis-aligned build-direction
candidates and recommend the best one by the manufacturing-tractability
metrics from Phase B (overhangs, wall thickness, unsupported spans) --
orchestration only, no new hard-geometry work (see SETUP.md B.9).

Each candidate is a rotation applied to a *copy* of the input mesh; every
candidate is then re-evaluated at the same default build direction
(0, 0, 1) -- rotating the part, not the build direction, so a selected
candidate is directly actionable ("rotate the part like this") rather than
requiring the reader to reinterpret a build-direction vector. Volume and
surface area are rotation-invariant and are not recomputed here (see
printlab.mesh.analyze); wall thickness is *also* rotation-invariant in
principle (ray-casting geometry doesn't depend on orientation) but is still
recomputed per candidate rather than assumed, since floating-point rounding
in the rotation matrix could in principle shift which rays land exactly on a
hard edge (see printlab.mesh.wall_thickness's own docstring on how sensitive
that estimate already is to edge cases).

Ranking uses an explicit, documented tie-break chain -- not a weighted score
(that is exactly what C.10 is deferred for, see printlab.schemas.evaluation):
minimize overhang_area_mm2, then maximize min_wall_thickness_mm, then
minimize max_unsupported_span_mm.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import trimesh

from printlab.determinism import hash_file
from printlab.mesh.bridges import estimate_max_unsupported_span_mm
from printlab.mesh.overhangs import DEFAULT_BUILD_DIRECTION, compute_overhangs
from printlab.mesh.wall_thickness import estimate_min_wall_thickness_mm
from printlab.schemas import OrientationCandidate, OrientationSearchReport


@dataclass(frozen=True)
class RotationSpec:
    label: str
    axis: tuple[float, float, float]
    degrees: float


#: The 6 axis-aligned orientations that put each of +X/-X/+Y/-Y/+Z/-Z as the
#: "up" direction (build_direction (0, 0, 1) after rotation) -- a full
#: continuous search is future work (see SETUP.md B.9); this is cheap (6
#: evaluations) and covers the common real cases, including examples/hook's
#: cantilever.
DEFAULT_CANDIDATES: tuple[RotationSpec, ...] = (
    RotationSpec("identity", (1.0, 0.0, 0.0), 0.0),
    RotationSpec("x+90", (1.0, 0.0, 0.0), 90.0),
    RotationSpec("x-90", (1.0, 0.0, 0.0), -90.0),
    RotationSpec("x+180", (1.0, 0.0, 0.0), 180.0),
    RotationSpec("y+90", (0.0, 1.0, 0.0), 90.0),
    RotationSpec("y-90", (0.0, 1.0, 0.0), -90.0),
)


def _rotate(mesh: trimesh.Trimesh, rotation: RotationSpec) -> trimesh.Trimesh:
    rotated = mesh.copy()
    if rotation.degrees != 0.0:
        matrix = trimesh.transformations.rotation_matrix(math.radians(rotation.degrees), rotation.axis)
        rotated.apply_transform(matrix)
    return rotated


def _evaluate(mesh: trimesh.Trimesh, rotation: RotationSpec) -> OrientationCandidate:
    rotated = _rotate(mesh, rotation)
    histogram, overhang_area = compute_overhangs(rotated, build_direction=DEFAULT_BUILD_DIRECTION)
    min_wall_thickness = estimate_min_wall_thickness_mm(rotated)
    max_span = estimate_max_unsupported_span_mm(rotated, build_direction=DEFAULT_BUILD_DIRECTION)
    return OrientationCandidate(
        label=rotation.label,
        rotation_axis=rotation.axis,
        rotation_degrees=rotation.degrees,
        overhang_area_mm2=overhang_area,
        overhang_histogram=histogram,
        min_wall_thickness_mm=min_wall_thickness,
        max_unsupported_span_mm=max_span,
    )


def search_orientations(
    mesh: trimesh.Trimesh, candidates: Sequence[RotationSpec] = DEFAULT_CANDIDATES
) -> list[OrientationCandidate]:
    """Evaluate every candidate rotation against a copy of `mesh`; `mesh`
    itself is never mutated."""
    return [_evaluate(mesh, rotation) for rotation in candidates]


def _wall_thickness_rank_value(value: float | None) -> float:
    # Missing means "ray casting produced no usable samples" (see
    # printlab.mesh.wall_thickness), i.e. worse than any real reading --
    # never a reason to prefer a candidate.
    return -math.inf if value is None else value


def _unsupported_span_rank_value(value: float | None) -> float:
    # Missing means "no overhang regions at all" (see printlab.mesh.bridges)
    # -- the best possible outcome, not unknown.
    return 0.0 if value is None else value


def rank_candidates(candidates: Sequence[OrientationCandidate]) -> tuple[int, str]:
    """Select the best candidate by an explicit tie-break chain: minimize
    overhang area, then maximize wall thickness, then minimize the longest
    unsupported span. Deliberately not a weighted score -- see
    printlab.schemas.evaluation for why that's deferred to C.10."""
    if not candidates:
        raise ValueError("rank_candidates() requires at least one candidate")

    def sort_key(candidate: OrientationCandidate) -> tuple[float, float, float]:
        return (
            candidate.overhang_area_mm2,
            -_wall_thickness_rank_value(candidate.min_wall_thickness_mm),
            _unsupported_span_rank_value(candidate.max_unsupported_span_mm),
        )

    selected_index = min(range(len(candidates)), key=lambda i: sort_key(candidates[i]))
    winner = candidates[selected_index]
    wall_thickness_display = (
        "unknown" if winner.min_wall_thickness_mm is None else f"{winner.min_wall_thickness_mm:.2f}"
    )
    span_display = (
        "0.00 (no overhangs)"
        if winner.max_unsupported_span_mm is None
        else f"{winner.max_unsupported_span_mm:.2f}"
    )
    reason = (
        f"'{winner.label}' minimizes overhang_area_mm2 ({winner.overhang_area_mm2:.2f}), "
        f"then maximizes min_wall_thickness_mm ({wall_thickness_display}), "
        f"then minimizes max_unsupported_span_mm ({span_display}) among {len(candidates)} candidates."
    )
    return selected_index, reason


def orient(
    stl_path: Path, candidates: Sequence[RotationSpec] = DEFAULT_CANDIDATES
) -> OrientationSearchReport:
    """Load an STL, evaluate every candidate rotation, and recommend one.

    Not part of `printlab all`'s critical path (like printlab.mesh.repair):
    explicitly invoked via `printlab orient`, mesh-metrics-only ranking (no
    re-slicing candidates -- see SETUP.md B.9 for that as a follow-up).
    """
    stl_path = Path(stl_path)
    input_sha256 = hash_file(stl_path)
    mesh = trimesh.load(stl_path, force="mesh")

    evaluated = search_orientations(mesh, candidates)
    selected_index, reason = rank_candidates(evaluated)

    return OrientationSearchReport(
        input_path=stl_path,
        input_sha256=input_sha256,
        candidates=evaluated,
        selected_index=selected_index,
        selection_reason=reason,
    )
