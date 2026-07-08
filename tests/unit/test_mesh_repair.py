"""Mesh repair tests using synthetic broken meshes -- no CAD kernel required,
same fast-lane rationale as tests/unit/test_mesh_analyze.py."""

from __future__ import annotations

from pathlib import Path

import trimesh

from printlab.mesh import repair


def _box_missing_one_face() -> trimesh.Trimesh:
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    return trimesh.Trimesh(vertices=box.vertices.copy(), faces=box.faces[1:].copy(), process=False)


def test_repair_skips_already_manifold_mesh(tmp_path: Path):
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    stl_path = tmp_path / "box.stl"
    box.export(stl_path)

    report = repair(stl_path)

    assert report.status.value == "ok"
    assert report.repair_attempted is False
    assert report.fixes_applied == []
    assert report.manifold_before is True
    assert report.manifold_after is True
    assert report.output_path is None


def test_repair_fills_a_single_missing_face(tmp_path: Path):
    broken = _box_missing_one_face()
    stl_path = tmp_path / "broken.stl"
    broken.export(stl_path)
    assert not broken.is_watertight  # sanity check the fixture is actually broken

    output_path = tmp_path / "repaired.stl"
    report = repair(stl_path, output_path=output_path)

    assert report.repair_attempted is True
    assert "filled_holes" in report.fixes_applied
    assert report.manifold_before is False
    assert report.manifold_after is True
    assert report.watertight_after is True
    assert report.status.value == "ok"
    assert report.output_path == output_path
    assert output_path.is_file()

    repaired_mesh = trimesh.load(output_path, force="mesh")
    assert repaired_mesh.is_watertight


def test_repaired_mesh_preserves_original_volume(tmp_path: Path):
    original = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    broken = _box_missing_one_face()
    stl_path = tmp_path / "broken.stl"
    broken.export(stl_path)
    output_path = tmp_path / "repaired.stl"

    repair(stl_path, output_path=output_path)

    repaired_mesh = trimesh.load(output_path, force="mesh")
    assert repaired_mesh.volume == original.volume


def test_repair_does_not_write_output_when_no_fixes_applied(tmp_path: Path):
    box = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    stl_path = tmp_path / "box.stl"
    box.export(stl_path)
    output_path = tmp_path / "repaired.stl"

    repair(stl_path, output_path=output_path)

    assert not output_path.exists()


def test_repair_missing_file_reports_error(tmp_path: Path):
    report = repair(tmp_path / "does_not_exist.stl")
    assert report.status.value == "error"
    assert any(e.code == "mesh_load_failed" for e in report.errors)
