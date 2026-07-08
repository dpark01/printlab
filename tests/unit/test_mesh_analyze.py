"""Mesh analysis tests using synthetic trimesh primitives -- no CAD kernel
(cadquery/OCP) required, so this stays in the CI fast lane."""

from __future__ import annotations

from pathlib import Path

import pytest
import trimesh

from printlab.mesh import analyze


def test_analyze_manifold_box(tmp_path: Path):
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    stl_path = tmp_path / "box.stl"
    box.export(stl_path)

    report = analyze(stl_path)

    assert report.status.value == "ok"
    assert report.manifold is True
    assert report.watertight is True
    assert report.volume_mm3 == pytest.approx(1000.0)
    assert report.surface_area_mm2 == pytest.approx(600.0)
    assert report.shell_count == 1
    assert report.self_intersecting is False
    # A box resting flush on the bed has no overhangs: top is upward-facing,
    # sides are vertical, bottom rests on the bed (see printlab.mesh.overhangs).
    assert report.overhang_area_mm2 == 0.0
    assert report.min_wall_thickness_mm == pytest.approx(10.0, abs=0.5)
    assert report.max_unsupported_span_mm is None


def test_analyze_two_disjoint_shells(tmp_path: Path):
    box_a = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    box_b = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    box_b.apply_translation((100.0, 0.0, 0.0))  # far away: no bbox overlap
    combined = trimesh.util.concatenate([box_a, box_b])
    stl_path = tmp_path / "two_boxes.stl"
    combined.export(stl_path)

    report = analyze(stl_path)

    assert report.shell_count == 2
    assert report.self_intersecting is False  # disjoint bounding boxes


def test_analyze_overlapping_shells_flagged_by_heuristic(tmp_path: Path):
    box_a = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    box_b = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    box_b.apply_translation((5.0, 0.0, 0.0))  # overlapping bounding boxes
    combined = trimesh.util.concatenate([box_a, box_b])
    stl_path = tmp_path / "overlapping_boxes.stl"
    combined.export(stl_path)

    report = analyze(stl_path)

    assert report.shell_count == 2
    assert report.self_intersecting is True
    assert report.self_intersection_count == 1


def test_analyze_missing_file_reports_error(tmp_path: Path):
    report = analyze(tmp_path / "does_not_exist.stl")
    assert report.status.value == "error"
    assert any(e.code == "mesh_load_failed" for e in report.errors)
