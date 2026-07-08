"""Overhang analysis tests using synthetic meshes with hand-computable
expected areas -- no CAD kernel required, same fast-lane rationale as
tests/unit/test_mesh_analyze.py."""

from __future__ import annotations

import trimesh

from printlab.mesh.overhangs import compute_overhangs


def test_a_plain_box_has_zero_overhang():
    """A box's top face is upward-facing, its sides are vertical, and its
    bottom face rests on the print bed -- none of that is an overhang."""
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    histogram, overhang_area = compute_overhangs(box)

    assert overhang_area == 0.0
    assert all(area == 0.0 for area in histogram.values())


def test_a_suspended_shelf_is_a_90_degree_overhang():
    """A flat shelf held up by a thin pillar: the shelf's underside is not
    at the mesh's minimum Z, so (unlike the pillar's own base) it must be
    counted -- a horizontal downward face is the 90-degrees-from-vertical
    case, the maximum overhang severity."""
    pillar = trimesh.creation.box(extents=(2.0, 2.0, 20.0))
    pillar.apply_translation((0.0, 0.0, 10.0))
    shelf = trimesh.creation.box(extents=(10.0, 10.0, 2.0))
    shelf.apply_translation((0.0, 0.0, 21.0))
    combined = trimesh.util.concatenate([pillar, shelf])

    histogram, overhang_area = compute_overhangs(combined)

    assert overhang_area == 100.0
    assert histogram["80-90"] == 100.0
    assert sum(histogram.values()) == 100.0


def test_threshold_controls_which_area_counts_as_overhang():
    pillar = trimesh.creation.box(extents=(2.0, 2.0, 20.0))
    pillar.apply_translation((0.0, 0.0, 10.0))
    shelf = trimesh.creation.box(extents=(10.0, 10.0, 2.0))
    shelf.apply_translation((0.0, 0.0, 21.0))
    combined = trimesh.util.concatenate([pillar, shelf])

    _, overhang_area_at_0 = compute_overhangs(combined, threshold_deg=0.0)
    _, overhang_area_at_91 = compute_overhangs(combined, threshold_deg=91.0)

    assert overhang_area_at_0 == 100.0  # everything downward-facing counts
    assert overhang_area_at_91 == 0.0  # nothing reaches an impossible threshold


def test_build_direction_changes_which_faces_are_downward_facing():
    """Flipping the build direction flips which face of a suspended shelf
    counts as the overhang -- and it must use a build-direction-relative
    "bed" (projection onto the build axis), not a hardcoded Z axis, since
    orientation search will call this with directions other than +Z."""
    pillar = trimesh.creation.box(extents=(2.0, 2.0, 20.0))
    pillar.apply_translation((0.0, 0.0, 10.0))
    shelf = trimesh.creation.box(extents=(10.0, 10.0, 2.0))
    shelf.apply_translation((0.0, 0.0, 21.0))
    combined = trimesh.util.concatenate([pillar, shelf])

    _, overhang_area_up = compute_overhangs(combined, build_direction=(0.0, 0.0, 1.0))
    _, overhang_area_down = compute_overhangs(combined, build_direction=(0.0, 0.0, -1.0))

    assert overhang_area_up == 100.0
    # Flipped: the shelf's top (100mm^2) now rests at the (flipped) "bed" and
    # is excluded, but the pillar's own top face -- a small 2x2mm^2 internal
    # step where it meets the shelf -- becomes a genuine tiny overhang in the
    # inverted orientation. concatenate() doesn't boolean-union the two
    # boxes, so that hidden face still exists in the mesh.
    assert overhang_area_down == 4.0
