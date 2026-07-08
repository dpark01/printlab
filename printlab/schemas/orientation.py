"""Orientation search artifact (B.9): printlab.mesh.orientation.orient() ->
orientation_search_report.json.

Ranking uses an explicit tie-break chain, not a weighted composite score --
see printlab.schemas.evaluation for why a single scalar is deliberately
deferred (C.10).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import PrintLabArtifact


class OrientationCandidate(BaseModel):
    """One candidate rotation and its re-evaluated manufacturing metrics.

    `rotation_axis`/`rotation_degrees` describe the rotation applied to a
    *copy* of the part before re-evaluating at the default build direction
    (0, 0, 1) -- see printlab.mesh.orientation. `None` on
    `min_wall_thickness_mm`/`max_unsupported_span_mm` carries the same
    meaning as in MeshReport (see printlab.schemas.mesh).
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    rotation_axis: tuple[float, float, float]
    rotation_degrees: float

    overhang_area_mm2: float
    overhang_histogram: dict[str, float] = Field(default_factory=dict)
    min_wall_thickness_mm: float | None = None
    max_unsupported_span_mm: float | None = None


class OrientationSearchReport(PrintLabArtifact):
    """printlab.mesh.orientation.orient() -> orientation_search_report.json.

    Not part of `printlab all`'s critical path (like mesh_repair_report.json)
    -- explicitly invoked via `printlab orient`. `selected_index` indexes
    into `candidates`; `selection_reason` documents the tie-break chain that
    picked it (see printlab.mesh.orientation.rank_candidates) rather than a
    weighted score.
    """

    model_config = ConfigDict(extra="forbid")

    input_path: Path
    input_sha256: str
    candidates: list[OrientationCandidate] = Field(default_factory=list)
    selected_index: int
    selection_reason: str
