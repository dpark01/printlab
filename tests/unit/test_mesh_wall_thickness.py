"""Wall thickness estimation tests using synthetic meshes with known
approximate thicknesses -- no CAD kernel required.

Expected values include tolerance for two known, documented biases (see
printlab.mesh.wall_thickness docstring): a slight overestimate from the
cone's angled rays on flat faces, and a slight underestimate from reporting
a low percentile rather than the strict minimum (deliberate, to reject
sharp-edge ray-casting artifacts).
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from printlab.mesh.wall_thickness import estimate_min_wall_thickness, estimate_min_wall_thickness_mm


def test_estimate_min_wall_thickness_agrees_with_scalar_wrapper():
    slab = trimesh.creation.box(extents=(50.0, 50.0, 2.0))
    estimate = estimate_min_wall_thickness(slab)
    assert estimate is not None
    assert estimate.value_mm == pytest.approx(estimate_min_wall_thickness_mm(slab))


def test_estimate_min_wall_thickness_locates_the_thin_dimension():
    # The slab's thin faces (normal along Z) should dominate the low
    # percentile, so the reported location's Z should sit near a cap, not
    # out on the flat X/Y sides.
    slab = trimesh.creation.box(extents=(50.0, 50.0, 2.0))
    estimate = estimate_min_wall_thickness(slab)
    assert estimate is not None
    location_z = estimate.location[2]
    assert abs(location_z) == pytest.approx(1.0, abs=0.6)  # box is centered, caps at z=+-1


def test_estimate_min_wall_thickness_returns_none_when_scalar_does():
    single_triangle = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False
    )
    assert estimate_min_wall_thickness(single_triangle) is None


def test_a_solid_box_reports_its_own_thickness():
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    thickness = estimate_min_wall_thickness_mm(box)
    assert thickness == pytest.approx(10.0, abs=0.5)


def test_a_thin_walled_box_reports_the_thinner_dimension():
    # A slab 2mm thick in Z, much larger in X/Y: thickness should read ~2mm,
    # not the much larger X/Y extents.
    slab = trimesh.creation.box(extents=(50.0, 50.0, 2.0))
    thickness = estimate_min_wall_thickness_mm(slab)
    assert thickness == pytest.approx(2.0, abs=0.3)


def test_a_single_sharp_edge_artifact_does_not_dominate_a_larger_part():
    """Regression test for the bug this module originally had: reporting the
    strict minimum across faces let a handful of sharp-edge-adjacent facets
    (present on ANY capped cylinder, not just fused/seamed geometry) report
    a spurious near-zero reading instead of the cylinder's true diameter."""
    cylinder = trimesh.creation.cylinder(radius=6.0, height=30.0, sections=64)
    thickness = estimate_min_wall_thickness_mm(cylinder)
    assert thickness is not None
    assert thickness > 8.0  # true diameter is 12mm; a buggy version read ~4.6mm


def test_open_mesh_with_no_ray_hits_returns_none():
    # A single triangle has no "inside" for a ray to traverse into.
    single_triangle = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]], process=False
    )
    assert estimate_min_wall_thickness_mm(single_triangle) is None


def test_congruent_shells_on_a_plate_read_like_the_single_part():
    """Regression test for the N-up-plate dedup fix (see
    docs/printlab-wall-thickness-scalability.md, fix #3): several disjoint
    copies of the same part, placed far apart on one plate, should read the
    same thickness as the lone part -- congruent shells broadcast a cached
    result rather than independently re-sampling."""
    box = trimesh.creation.box(extents=(50.0, 50.0, 2.0))
    solo_thickness = estimate_min_wall_thickness_mm(box)

    copies = []
    for i in range(5):
        copy = box.copy()
        copy.apply_translation((i * 200.0, 0.0, 0.0))  # far apart: no bbox overlap
        copies.append(copy)
    plate = trimesh.util.concatenate(copies)

    plate_thickness = estimate_min_wall_thickness_mm(plate)
    assert plate_thickness == pytest.approx(solo_thickness)


def test_a_shell_reads_the_same_thickness_regardless_of_its_neighbor():
    """Regression test for the cross-shell ray-leak fix (fix #1): a shell's
    own reading must not depend on what else shares the plate -- each shell
    is ray-cast against its own BVH only."""
    slab = trimesh.creation.box(extents=(50.0, 50.0, 2.0))
    solo_thickness = estimate_min_wall_thickness_mm(slab)

    neighbor = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    neighbor.apply_translation((100.0, 0.0, 0.0))
    plate = trimesh.util.concatenate([slab, neighbor])

    plate_result = estimate_min_wall_thickness(plate)
    assert plate_result is not None
    # The slab's reading must be unperturbed by sharing a plate with a much
    # thicker neighbor a fixed distance away.
    assert plate_result.value_mm == pytest.approx(solo_thickness, abs=0.3)


def test_sampling_below_a_low_face_cap_is_bounded_and_deterministic():
    """Regression test for the capped-sample fix (fix #2): forcing a tiny
    per-shell face budget on a high-poly part must not crash, must still
    reject the sharp-edge artifact (see
    test_a_single_sharp_edge_artifact_does_not_dominate_a_larger_part above),
    and must be reproducible across repeated calls."""
    cylinder = trimesh.creation.cylinder(radius=6.0, height=30.0, sections=256)
    assert len(cylinder.faces) > 500

    first = estimate_min_wall_thickness_mm(cylinder, max_sampled_faces_per_shell=100)
    second = estimate_min_wall_thickness_mm(cylinder, max_sampled_faces_per_shell=100)
    assert first is not None
    assert first == second
    assert first > 8.0  # true diameter is 12mm; a buggy version read ~4.6mm


def test_degenerate_zero_area_face_is_excluded_not_fatal():
    """Regression test for the NaN-normal robustness gap (a zero-area face's
    normal can't be normalized -- a 0/0 division -- which previously
    propagated into ray directions and crashed the ray-mesh intersector
    outright instead of just being skipped)."""
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    vertices = np.vstack([box.vertices, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]])
    faces = np.vstack([box.faces, [[8, 9, 10]]])  # zero-area (collinear) triangle
    mesh_with_degenerate_face = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)

    result = estimate_min_wall_thickness(mesh_with_degenerate_face)
    assert result is not None
    assert np.isfinite(result.value_mm)
    assert result.value_mm == pytest.approx(10.0, abs=0.5)
