"""Wall thickness estimation via ray casting (a "shape diameter function"
approximation).

For each face, a small cone of rays is cast from its centroid along the
inward normal; the *median* distance to the first opposite surface hit
approximates the local material thickness there. A single ray per face was
tried first and rejected: at sharp edges (e.g. the rim of a cylinder, or
where two fused primitives meet), a lone ray can graze a nearby facet of the
same local feature instead of the true opposite wall, producing spurious
near-zero readings.

Reporting the strict minimum across all faces' medians was *also* tried and
rejected: even with the cone+median fix, a handful of faces immediately
adjacent to a sharp edge still produce artificially low readings (verified
directly -- a single plain capped cylinder with no seam at all, radius 6mm,
reported a "minimum thickness" of ~4.6mm instead of the true ~12mm diameter,
entirely from 1-2% of its faces sitting right at the cap/wall rim; the 5th
percentile of the same data lands at ~10.9mm, converging fully by the 10th).
This is a known failure mode of naive per-facet SDF estimation: "thickness"
via opposing-ray-casting isn't well-defined right at a sharp corner, where
the local geometry isn't slab-like. Reporting a low percentile instead of
the strict minimum is the standard mitigation -- it stays sensitive to a
genuinely thin *region* (many faces reading low) while not being hijacked by
a handful of edge-adjacent outliers. This means the reported value can be
an *overestimate* of the true worst-case point thickness by design; treat it
as "the thin end of the bulk of the surface," not an exact minimum.

Faces that produce no hits at all (an open/non-manifold mesh) are excluded
entirely rather than treated as zero thickness; a caller should treat `None`
(nothing sampled successfully) as "unknown," not "fine."
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh


@dataclass(frozen=True)
class WallThicknessEstimate:
    """`estimate_min_wall_thickness`'s result: the percentile thickness value
    plus *where* it was sampled, so a caller can localize a thin region
    instead of only knowing a scalar exists."""

    value_mm: float
    #: Centroid of the face whose per-face median reading is closest to
    #: `value_mm` -- i.e. a representative point in the thin region, not
    #: necessarily the single thinnest face (percentile, not minimum; see
    #: module docstring).
    location: tuple[float, float, float]

#: How far to nudge each ray's origin inside the surface before casting, so
#: it doesn't immediately self-intersect the face it started on.
DEFAULT_SAMPLE_EPSILON_MM = 1e-3

#: Cone half-angle and ray count around each face's inward normal. A wider
#: cone was tried and made the sharp-edge artifact *worse* (more of the
#: cone's rays clip the nearby wrong surface, pulling the per-face median
#: down too) -- narrow-cone-plus-percentile outperforms wide-cone-plus-median.
DEFAULT_CONE_HALF_ANGLE_DEG = 5.0
DEFAULT_CONE_SIDE_RAYS = 6

#: Reported thickness is this percentile of all per-face median readings,
#: not the strict minimum -- see module docstring for why.
DEFAULT_PERCENTILE = 5.0

#: Rays are cast in batches of at most this many rather than all at once.
#: trimesh's non-embree (pure rtree) RayMeshIntersector's per-ray memory cost
#: on intersects_location() is roughly constant (measured directly on
#: examples/canoe's 14.4k-face hull: ~0.3-0.4MB/ray, scaling ~linearly from
#: 200 to 5,000 rays) but that constant is large enough on thin/curved
#: geometry with many AABB-overlapping candidate triangles per ray that all
#: ~101k rays at once peaked at ~16-19GB RSS -- enough to OOM-kill a
#: standard CI runner silently (a killed process produces no traceback, just
#: an abrupt exit). 2,000 rays/batch brings canoe's full `run_check` down to
#: ~3.3GB peak RSS (comfortably under a 7GB CI runner) with an identical
#: result to one giant batch: same rays, same hits, just accumulated
#: incrementally.
_MAX_RAYS_PER_BATCH = 2_000


def _cone_directions(normals: np.ndarray, half_angle_deg: float, side_rays: int) -> np.ndarray:
    """Return ray directions with shape (side_rays + 1, len(normals), 3):
    each face's own inward normal, plus `side_rays` directions arranged
    evenly around a cone of `half_angle_deg` around it."""
    unit_normals = normals / np.linalg.norm(normals, axis=1, keepdims=True)

    # An arbitrary reference vector not (nearly) parallel to any normal, to
    # build an orthonormal basis {normal, t1, t2} per face.
    reference = np.where(
        np.abs(unit_normals[:, 0:1]) < 0.9,
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
    )
    t1 = np.cross(unit_normals, reference)
    t1 /= np.linalg.norm(t1, axis=1, keepdims=True)
    t2 = np.cross(unit_normals, t1)

    half_angle_rad = np.radians(half_angle_deg)
    directions = [unit_normals]
    for k in range(side_rays):
        phi = 2 * np.pi * k / side_rays
        cone_dir = unit_normals * np.cos(half_angle_rad) + (t1 * np.cos(phi) + t2 * np.sin(phi)) * np.sin(
            half_angle_rad
        )
        directions.append(cone_dir)
    return np.stack(directions, axis=0)


def estimate_min_wall_thickness(
    mesh: trimesh.Trimesh,
    epsilon_mm: float = DEFAULT_SAMPLE_EPSILON_MM,
    cone_half_angle_deg: float = DEFAULT_CONE_HALF_ANGLE_DEG,
    cone_side_rays: int = DEFAULT_CONE_SIDE_RAYS,
    percentile: float = DEFAULT_PERCENTILE,
) -> WallThicknessEstimate | None:
    """Return the estimated wall thickness (the `percentile`-th percentile of
    per-face readings -- see module docstring for why this is not the strict
    minimum) plus a representative location, or None if no face produced a
    usable ray hit (e.g. a badly broken mesh)."""
    centroids = mesh.triangles_center
    normals = mesh.face_normals
    num_faces = len(centroids)

    # Inward directions: face_normals point outward, and casting must go
    # into the solid to find the opposite wall.
    direction_sets = _cone_directions(-normals, cone_half_angle_deg, cone_side_rays)
    num_directions = direction_sets.shape[0]

    # Nudge FORWARD along each ray's own cast direction (not backward): a
    # backward nudge puts the origin exactly `epsilon_mm` before the
    # centroid *on the same ray line*, so the ray immediately re-crosses
    # its own starting face at t=epsilon_mm -- this was tried and produced
    # exactly-epsilon "thickness" on every face, confirming the bug.
    origins = centroids[np.newaxis, :, :] + direction_sets * epsilon_mm
    flat_origins = origins.reshape(-1, 3)
    flat_directions = direction_sets.reshape(-1, 3)
    # Matches the (num_directions, num_faces, 3) -> (-1, 3) row-major flattening.
    face_index_for_ray = np.tile(np.arange(num_faces), num_directions)

    per_face_hits: dict[int, list[float]] = {}
    total_rays = flat_origins.shape[0]
    for start in range(0, total_rays, _MAX_RAYS_PER_BATCH):
        end = min(start + _MAX_RAYS_PER_BATCH, total_rays)
        batch_origins = flat_origins[start:end]
        locations, index_ray, _index_tri = mesh.ray.intersects_location(
            ray_origins=batch_origins, ray_directions=flat_directions[start:end], multiple_hits=False
        )
        if len(locations) == 0:
            continue
        hit_face_indices = face_index_for_ray[start:end][index_ray]
        hit_distances = np.linalg.norm(locations - batch_origins[index_ray], axis=1)
        for face_idx, distance in zip(hit_face_indices, hit_distances, strict=True):
            per_face_hits.setdefault(int(face_idx), []).append(float(distance))

    if not per_face_hits:
        return None
    # Keep face indices alongside their medians (instead of collapsing to
    # `.values()`) so the percentile value can be traced back to a location.
    face_ids = list(per_face_hits.keys())
    per_face_medians = [float(np.median(per_face_hits[face_id])) for face_id in face_ids]
    value_mm = float(np.percentile(per_face_medians, percentile))
    # No single face reads exactly at the percentile value; report the
    # location of whichever face's median is closest to it as a
    # representative point in the thin region.
    closest = int(np.argmin(np.abs(np.array(per_face_medians) - value_mm)))
    location = tuple(float(c) for c in centroids[face_ids[closest]])
    return WallThicknessEstimate(value_mm=value_mm, location=location)


def estimate_min_wall_thickness_mm(
    mesh: trimesh.Trimesh,
    epsilon_mm: float = DEFAULT_SAMPLE_EPSILON_MM,
    cone_half_angle_deg: float = DEFAULT_CONE_HALF_ANGLE_DEG,
    cone_side_rays: int = DEFAULT_CONE_SIDE_RAYS,
    percentile: float = DEFAULT_PERCENTILE,
) -> float | None:
    """Backward-compatible scalar wrapper around `estimate_min_wall_thickness`
    -- see that function's docstring. Used by callers (e.g. orientation
    search) that only need the value, not its location."""
    estimate = estimate_min_wall_thickness(
        mesh,
        epsilon_mm=epsilon_mm,
        cone_half_angle_deg=cone_half_angle_deg,
        cone_side_rays=cone_side_rays,
        percentile=percentile,
    )
    return estimate.value_mm if estimate is not None else None
