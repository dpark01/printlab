"""Unsupported span estimation tests using synthetic meshes with
hand-computable expected spans -- no CAD kernel required."""

from __future__ import annotations

import pytest
import trimesh

from printlab.mesh.bridges import estimate_max_unsupported_span_mm


def test_a_plain_box_has_no_unsupported_span():
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    assert estimate_max_unsupported_span_mm(box) is None


def test_a_suspended_shelf_spans_its_own_diagonal():
    """Same rig as tests/unit/test_mesh_overhangs.py: a 10x10mm shelf held
    up by a thin pillar. Its connected underside should span its diagonal,
    sqrt(10^2 + 10^2)."""
    pillar = trimesh.creation.box(extents=(2.0, 2.0, 20.0))
    pillar.apply_translation((0.0, 0.0, 10.0))
    shelf = trimesh.creation.box(extents=(10.0, 10.0, 2.0))
    shelf.apply_translation((0.0, 0.0, 21.0))
    combined = trimesh.util.concatenate([pillar, shelf])

    span = estimate_max_unsupported_span_mm(combined)
    assert span == pytest.approx(14.142135623730951)


def test_two_disjoint_overhangs_report_the_larger_span():
    """Two separate suspended shelves of different sizes, far enough apart
    that their undersides are NOT face-adjacent (different connected
    components) -- the larger one's span must win, not their sum."""
    small_pillar = trimesh.creation.box(extents=(2.0, 2.0, 20.0))
    small_pillar.apply_translation((0.0, 0.0, 10.0))
    small_shelf = trimesh.creation.box(extents=(6.0, 6.0, 2.0))
    small_shelf.apply_translation((0.0, 0.0, 21.0))

    big_pillar = trimesh.creation.box(extents=(2.0, 2.0, 20.0))
    big_pillar.apply_translation((100.0, 0.0, 10.0))
    big_shelf = trimesh.creation.box(extents=(20.0, 20.0, 2.0))
    big_shelf.apply_translation((100.0, 0.0, 21.0))

    combined = trimesh.util.concatenate([small_pillar, small_shelf, big_pillar, big_shelf])
    span = estimate_max_unsupported_span_mm(combined)

    big_shelf_diagonal = (20.0**2 + 20.0**2) ** 0.5
    assert span == pytest.approx(big_shelf_diagonal)
