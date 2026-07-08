"""Orientation search tests reusing the suspended-shelf rig from
test_mesh_overhangs.py/test_mesh_bridges.py -- no CAD kernel required."""

from __future__ import annotations

import pytest
import trimesh

from printlab.mesh.orientation import DEFAULT_CANDIDATES, RotationSpec, rank_candidates, search_orientations


def _suspended_shelf() -> trimesh.Trimesh:
    pillar = trimesh.creation.box(extents=(2.0, 2.0, 20.0))
    pillar.apply_translation((0.0, 0.0, 10.0))
    shelf = trimesh.creation.box(extents=(10.0, 10.0, 2.0))
    shelf.apply_translation((0.0, 0.0, 21.0))
    return trimesh.util.concatenate([pillar, shelf])


def test_default_candidates_cover_six_axis_aligned_orientations():
    assert len(DEFAULT_CANDIDATES) == 6


def test_identity_candidate_matches_the_default_orientation_metrics():
    mesh = _suspended_shelf()
    candidates = search_orientations(mesh, candidates=(RotationSpec("identity", (1.0, 0.0, 0.0), 0.0),))
    assert candidates[0].overhang_area_mm2 == 100.0


def test_rotating_180_about_x_reproduces_the_flipped_build_direction_result():
    """Cross-check against test_mesh_overhangs.py's build_direction=(0,0,-1)
    case: rotating the mesh 180 degrees about X and re-evaluating at the
    default build direction must land on the same known-good value."""
    mesh = _suspended_shelf()
    candidates = search_orientations(mesh)
    flipped = next(c for c in candidates if c.label == "x+180")
    assert flipped.overhang_area_mm2 == pytest.approx(4.0)


def test_search_recommends_rotating_away_from_the_worst_overhang():
    mesh = _suspended_shelf()
    candidates = search_orientations(mesh)
    selected_index, reason = rank_candidates(candidates)
    winner = candidates[selected_index]

    assert winner.overhang_area_mm2 < 100.0
    assert winner.label != "identity"
    assert "overhang_area_mm2" in reason


def test_a_plain_box_is_orientation_indifferent():
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    candidates = search_orientations(box)
    assert all(c.overhang_area_mm2 == 0.0 for c in candidates)
    selected_index, _ = rank_candidates(candidates)
    assert candidates[selected_index].overhang_area_mm2 == 0.0


def test_search_never_mutates_the_input_mesh():
    mesh = _suspended_shelf()
    original_vertices = mesh.vertices.copy()
    search_orientations(mesh)
    assert (mesh.vertices == original_vertices).all()


def test_rank_candidates_requires_at_least_one_candidate():
    with pytest.raises(ValueError, match="at least one candidate"):
        rank_candidates([])
