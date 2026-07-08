"""Wall thickness estimation tests using synthetic meshes with known
approximate thicknesses -- no CAD kernel required.

Expected values include tolerance for two known, documented biases (see
printlab.mesh.wall_thickness docstring): a slight overestimate from the
cone's angled rays on flat faces, and a slight underestimate from reporting
a low percentile rather than the strict minimum (deliberate, to reject
sharp-edge ray-casting artifacts).
"""

from __future__ import annotations

import pytest
import trimesh

from printlab.mesh.wall_thickness import estimate_min_wall_thickness_mm


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
