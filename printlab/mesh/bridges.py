"""Unsupported span ("bridge") length estimation.

Reuses the same downward-facing/bed-resting face classification as
printlab.mesh.overhangs, then groups *connected* overhang faces into regions
using face adjacency (trimesh.graph.connected_components) and measures each
region's extent in the plane perpendicular to the build direction. The
largest such extent across all regions is reported as the longest
unsupported span in the part.

This is a coarser approximation than the overhang histogram it builds on:
"span" here is a region's projected bounding-box diagonal, not the true
geometric diameter of an arbitrarily-shaped connected region, and it does
not distinguish a genuine two-wall bridge (which can safely span much
further than a one-sided cantilever, given adequate cooling) from a
free-hanging overhang -- that distinction needs real connectivity-to-support
reasoning this module doesn't attempt. Treat the reported value as "the
longest contiguous unsupported region," not a validated "this needs support"
threshold; PrintLab does not yet model a per-material safe bridge length to
compare it against (see printlab.schemas.profiles.MaterialProfile).
"""

from __future__ import annotations

import numpy as np
import trimesh

from printlab.mesh.overhangs import DEFAULT_BUILD_DIRECTION, classify_overhang_faces


def _projected_span(vertices: np.ndarray, build_dir: np.ndarray) -> float:
    """Bounding-box diagonal of `vertices` projected onto the plane
    perpendicular to `build_dir` -- a cheap, honest proxy for "how far this
    region stretches horizontally," not an exact geometric diameter."""
    projected = vertices - np.outer(vertices @ build_dir, build_dir)
    extent = projected.max(axis=0) - projected.min(axis=0)
    return float(np.linalg.norm(extent))


def estimate_max_unsupported_span_mm(
    mesh: trimesh.Trimesh, build_direction: tuple[float, float, float] = DEFAULT_BUILD_DIRECTION
) -> float | None:
    """Return the longest contiguous unsupported (downward-facing,
    non-bed-resting) region's horizontal span in mm, or None if there are no
    such regions at all (a part with zero overhangs)."""
    build_dir = np.asarray(build_direction, dtype=float)
    build_dir = build_dir / np.linalg.norm(build_dir)

    overhang_mask = classify_overhang_faces(mesh, build_dir)
    overhang_face_indices = np.where(overhang_mask)[0]
    if len(overhang_face_indices) == 0:
        return None

    adjacency = mesh.face_adjacency
    both_in_overhang = overhang_mask[adjacency[:, 0]] & overhang_mask[adjacency[:, 1]]
    restricted_edges = adjacency[both_in_overhang]

    groups = trimesh.graph.connected_components(restricted_edges, nodes=overhang_face_indices, min_len=1)
    if not groups:
        return None

    max_span = 0.0
    for group in groups:
        group_vertices = mesh.vertices[mesh.faces[group]].reshape(-1, 3)
        max_span = max(max_span, _projected_span(group_vertices, build_dir))
    return max_span
