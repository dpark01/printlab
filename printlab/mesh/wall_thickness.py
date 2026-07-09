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

Multi-part meshes (e.g. a print-bed plate of several disjoint solids in one
STL): rays are cast independently *within* each connected component (see
`_iter_shells`), never against a BVH spanning the whole input. This is both a
correctness fix (a ray searching for its own opposite wall could otherwise
leak across the gap to a nearby-but-unrelated shell and report a bogus
distance) and the main scalability fix (each shell's ray-cast cost depends
only on that shell's own face count, not on how many other parts share the
plate). Per-shell results are pooled before the final percentile, so the
reported value is still a single plate-wide estimate. See
`docs/printlab-wall-thickness-scalability.md` for the full writeup.

Two more measures keep large/repetitive designs bounded: each shell samples
at most `DEFAULT_MAX_SAMPLED_FACES_PER_SHELL` faces (area-weighted, so large
flat faces aren't over/under-represented relative to many small ones -- see
`_select_face_indices`), and shells that are geometric duplicates of one
already analyzed (e.g. an N-up plate of one part) reuse that shell's readings
instead of re-casting rays against an identical shape (see
`_shell_fingerprint`).
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
#: incrementally. This bound is per shell (see `_iter_shells`), not per mesh
#: -- a multi-part plate no longer multiplies a single shell's batch count.
_MAX_RAYS_PER_BATCH = 2_000

#: Ceiling on how many faces of a single shell are sampled for ray-casting.
#: Set well above any current example part (examples/canoe's hull is ~14.4k
#: faces) so no existing single-part design changes value; this only engages
#: for a genuinely huge shell, turning "cost scales with shell size" into "cost
#: has a fixed per-shell ceiling" per the scalability writeup's fix #2.
DEFAULT_MAX_SAMPLED_FACES_PER_SHELL = 20_000

#: Fixed seed for the area-weighted face sample below the cap, so repeated
#: calls on the same mesh are reproducible (see determinism.py / the
#: run-to-run hash-identical golden tests).
_SAMPLE_RNG_SEED = 0


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


def _iter_shells(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh]:
    """Split `mesh` into its connected components so ray-casting can be run
    independently within each one (see module docstring). Falls back to
    treating the whole mesh as a single shell if splitting fails or reports
    nothing -- e.g. a totally empty (0-face) mesh, which trimesh's splitter
    doesn't handle -- so callers still get a graceful `None` instead of a
    crash, matching this module's existing "no usable samples -> None"
    contract."""
    try:
        shells = list(mesh.split(only_watertight=False))
    except Exception:  # noqa: BLE001 - degrade to "treat as one shell", not a crash
        return [mesh]
    return shells if shells else [mesh]


def _shell_fingerprint(shell: trimesh.Trimesh) -> str:
    """Pose-invariant identity for a shell, used to skip re-ray-casting a
    shape congruent to one already analyzed (e.g. an N-up plate of one
    part) -- see module docstring. `identifier_hash` is unaffected by the
    shell's position/rotation but differs for a genuinely different shape."""
    return str(shell.identifier_hash)


def _select_face_indices(
    shell: trimesh.Trimesh, max_faces: int, seed: int
) -> np.ndarray:
    """Return the indices of faces to ray-cast for `shell`: every valid face
    if the shell is at or under `max_faces`, otherwise an area-weighted
    sample of exactly `max_faces` of them (so large flat faces aren't
    over/under-represented relative to many small ones -- see module
    docstring). "Valid" excludes zero-area/degenerate faces, whose normal
    can't be normalized (a `0/0` division) and would otherwise propagate NaN
    into ray directions and break the ray-mesh intersector outright."""
    areas = shell.area_faces
    normals = shell.face_normals
    valid = (areas > 0) & np.isfinite(areas) & np.isfinite(normals).all(axis=1)
    valid_indices = np.nonzero(valid)[0]
    if valid_indices.size <= max_faces:
        return valid_indices

    rng = np.random.default_rng(seed)
    weights = areas[valid_indices]
    probabilities = weights / weights.sum()
    sampled = rng.choice(valid_indices, size=max_faces, replace=False, p=probabilities)
    return np.sort(sampled)


def _shell_face_medians(
    shell: trimesh.Trimesh,
    face_indices: np.ndarray,
    epsilon_mm: float,
    cone_half_angle_deg: float,
    cone_side_rays: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Ray-cast `face_indices` of `shell` against `shell`'s own BVH only
    (never a neighboring shell's) and return that shell's per-face median
    hit distances alongside the matching face centroids, for whichever faces
    produced at least one hit. Both returned arrays are empty if none did."""
    if face_indices.size == 0:
        return np.empty(0), np.empty((0, 3))

    centroids = shell.triangles_center[face_indices]
    normals = shell.face_normals[face_indices]
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
    local_face_index_for_ray = np.tile(np.arange(num_faces), num_directions)

    per_face_hits: dict[int, list[float]] = {}
    total_rays = flat_origins.shape[0]
    for start in range(0, total_rays, _MAX_RAYS_PER_BATCH):
        end = min(start + _MAX_RAYS_PER_BATCH, total_rays)
        batch_origins = flat_origins[start:end]
        locations, index_ray, _index_tri = shell.ray.intersects_location(
            ray_origins=batch_origins, ray_directions=flat_directions[start:end], multiple_hits=False
        )
        if len(locations) == 0:
            continue
        hit_local_indices = local_face_index_for_ray[start:end][index_ray]
        hit_distances = np.linalg.norm(locations - batch_origins[index_ray], axis=1)
        for local_idx, distance in zip(hit_local_indices, hit_distances, strict=True):
            per_face_hits.setdefault(int(local_idx), []).append(float(distance))

    if not per_face_hits:
        return np.empty(0), np.empty((0, 3))
    local_ids = list(per_face_hits.keys())
    medians = np.array([float(np.median(per_face_hits[local_id])) for local_id in local_ids])
    matched_centroids = centroids[local_ids]
    return medians, matched_centroids


def estimate_min_wall_thickness(
    mesh: trimesh.Trimesh,
    epsilon_mm: float = DEFAULT_SAMPLE_EPSILON_MM,
    cone_half_angle_deg: float = DEFAULT_CONE_HALF_ANGLE_DEG,
    cone_side_rays: int = DEFAULT_CONE_SIDE_RAYS,
    percentile: float = DEFAULT_PERCENTILE,
    max_sampled_faces_per_shell: int = DEFAULT_MAX_SAMPLED_FACES_PER_SHELL,
) -> WallThicknessEstimate | None:
    """Return the estimated wall thickness (the `percentile`-th percentile of
    per-face readings -- see module docstring for why this is not the strict
    minimum) plus a representative location, or None if no face produced a
    usable ray hit (e.g. a badly broken mesh).

    `mesh` is split into connected components and each is ray-cast
    independently -- see module docstring -- before pooling every shell's
    per-face medians into one plate-wide percentile."""
    pooled_medians: list[np.ndarray] = []
    pooled_centroids: list[np.ndarray] = []
    # Congruent-shell cache: reuse a previously-analyzed shell's readings for
    # any later shell with the same fingerprint instead of re-ray-casting an
    # identical shape (see module docstring, `_shell_fingerprint`). Caching
    # the (medians, centroids) arrays -- not just the final scalar -- means a
    # duplicate still contributes its own weight to the pooled percentile,
    # exactly as if it had been ray-cast independently.
    seen: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for shell in _iter_shells(mesh):
        fingerprint = _shell_fingerprint(shell)
        if fingerprint in seen:
            medians, centroids = seen[fingerprint]
        else:
            face_indices = _select_face_indices(shell, max_sampled_faces_per_shell, _SAMPLE_RNG_SEED)
            medians, centroids = _shell_face_medians(
                shell, face_indices, epsilon_mm, cone_half_angle_deg, cone_side_rays
            )
            seen[fingerprint] = (medians, centroids)
        if medians.size:
            pooled_medians.append(medians)
            pooled_centroids.append(centroids)

    if not pooled_medians:
        return None
    per_face_medians = np.concatenate(pooled_medians)
    all_centroids = np.concatenate(pooled_centroids, axis=0)

    value_mm = float(np.percentile(per_face_medians, percentile))
    # No single face reads exactly at the percentile value; report the
    # location of whichever face's median is closest to it as a
    # representative point in the thin region.
    closest = int(np.argmin(np.abs(per_face_medians - value_mm)))
    location = tuple(float(c) for c in all_centroids[closest])
    return WallThicknessEstimate(value_mm=value_mm, location=location)


def estimate_min_wall_thickness_mm(
    mesh: trimesh.Trimesh,
    epsilon_mm: float = DEFAULT_SAMPLE_EPSILON_MM,
    cone_half_angle_deg: float = DEFAULT_CONE_HALF_ANGLE_DEG,
    cone_side_rays: int = DEFAULT_CONE_SIDE_RAYS,
    percentile: float = DEFAULT_PERCENTILE,
    max_sampled_faces_per_shell: int = DEFAULT_MAX_SAMPLED_FACES_PER_SHELL,
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
        max_sampled_faces_per_shell=max_sampled_faces_per_shell,
    )
    return estimate.value_mm if estimate is not None else None
