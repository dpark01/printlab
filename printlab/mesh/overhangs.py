"""Overhang analysis: bucket downward-facing surface area by angle from the
vertical build axis.

This is a genuinely hard problem in general -- true overhang/support
analysis needs a slicer's full toolpath reasoning (island connectivity,
bridging, per-layer support geometry). This module implements a bounded,
honest approximation: per-face-normal classification against a single
assumed build direction, with one refinement -- faces resting on the print
bed (all vertices at the minimum projection onto the build axis, generalizing
"minimum Z" to work for any build direction) are excluded, since a downward-
facing face sitting on the bed needs no support even though its normal
points straight down. It does NOT know about bridging (a downward face
spanning between two supported walls needs no support either, up to a
material-dependent bridge length -- see the deferred bridge-detection work)
or about supports the slicer might add for unrelated reasons.

Angle convention: 0 degrees = a vertical wall (safe), 90 degrees = a
horizontal downward-facing ceiling (maximum overhang severity) -- matching
how slicer "support overhang threshold" settings are conventionally
described (angle from vertical).
"""

from __future__ import annotations

import numpy as np
import trimesh

#: Printer build direction: +Z, matching PrintLab's mm/Z-up convention.
DEFAULT_BUILD_DIRECTION = (0.0, 0.0, 1.0)

#: Typical slicer default "support overhang threshold" (angle from vertical
#: beyond which a downward-facing surface is considered to need support).
DEFAULT_OVERHANG_THRESHOLD_DEG = 45.0

_BUCKET_WIDTH_DEG = 10
_BUCKET_LOWER_EDGES = list(range(0, 90, _BUCKET_WIDTH_DEG))  # 0, 10, ..., 80

#: A face resting on the print bed is excluded from overhang accounting if
#: all its vertices lie within this distance (mm) of the bed level (the
#: mesh's minimum projection onto the build axis).
_BED_CONTACT_TOLERANCE_MM = 1e-4


def _bucket_label(lower_edge: int) -> str:
    return f"{lower_edge}-{lower_edge + _BUCKET_WIDTH_DEG}"


def classify_overhang_faces(mesh: trimesh.Trimesh, build_dir: np.ndarray) -> np.ndarray:
    """Boolean mask: which faces are downward-facing and not resting on the
    print bed. `build_dir` must already be a normalized (unit) vector.

    Shared by compute_overhangs() and printlab.mesh.bridges so both modules
    agree on exactly what counts as "an overhang" -- see module docstring
    for the bed-contact refinement and its rationale.
    """
    normals = mesh.face_normals

    # Positive for faces whose outward normal opposes the build direction
    # (i.e. points at least partly "down").
    downward_component = -(normals @ build_dir)
    downward_mask = downward_component > 1e-9

    # Generalizes "minimum Z" to "minimum projection onto the build axis" so
    # this is correct for any build_direction, not just +Z -- important
    # since orientation search (trying multiple rotations) will call this
    # with directions other than the default.
    vertex_projections = mesh.vertices @ build_dir
    bed_level = vertex_projections.min()
    face_vertex_projections = vertex_projections[mesh.faces]
    bed_resting_mask = np.all(
        np.abs(face_vertex_projections - bed_level) <= _BED_CONTACT_TOLERANCE_MM, axis=1
    )

    return downward_mask & ~bed_resting_mask


def compute_overhangs(
    mesh: trimesh.Trimesh,
    build_direction: tuple[float, float, float] = DEFAULT_BUILD_DIRECTION,
    threshold_deg: float = DEFAULT_OVERHANG_THRESHOLD_DEG,
) -> tuple[dict[str, float], float]:
    """Return (histogram, overhang_area_mm2_at_or_beyond_threshold).

    `histogram` maps a "{lo}-{hi}" degree-bucket label to the downward-facing
    surface area (mm^2) whose angle from vertical falls in that bucket.
    Bed-resting faces and non-downward-facing faces are excluded entirely
    (not just bucketed at 0) -- see module docstring.
    """
    build_dir = np.asarray(build_direction, dtype=float)
    build_dir = build_dir / np.linalg.norm(build_dir)

    areas = mesh.area_faces
    overhang_mask = classify_overhang_faces(mesh, build_dir)
    downward_component = -(mesh.face_normals @ build_dir)

    histogram = {_bucket_label(lo): 0.0 for lo in _BUCKET_LOWER_EDGES}
    overhang_area_at_threshold = 0.0

    if overhang_mask.any():
        clipped = np.clip(downward_component[overhang_mask], -1.0, 1.0)
        angles_from_vertical = np.degrees(np.arcsin(clipped))
        face_areas = areas[overhang_mask]

        bucket_indices = np.clip(
            (angles_from_vertical // _BUCKET_WIDTH_DEG).astype(int),
            0,
            len(_BUCKET_LOWER_EDGES) - 1,
        )
        area_per_bucket = np.bincount(bucket_indices, weights=face_areas, minlength=len(_BUCKET_LOWER_EDGES))
        for lo, area in zip(_BUCKET_LOWER_EDGES, area_per_bucket, strict=True):
            histogram[_bucket_label(lo)] = float(area)

        overhang_area_at_threshold = float(face_areas[angles_from_vertical >= threshold_deg].sum())

    return histogram, overhang_area_at_threshold
