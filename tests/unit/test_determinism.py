from __future__ import annotations

from pathlib import Path

from printlab.determinism import (
    canonical_json,
    hash_artifact,
    hash_file,
    hash_mapping,
    normalize,
)
from printlab.schemas import BBox, MeshReport


def test_normalize_strips_volatile_keys():
    data = {"created_at": "2024-01-01T00:00:00Z", "value": 1.0}
    assert normalize(data) == {"value": 1.0}


def test_normalize_rounds_floats():
    data = {"x": 1.00000012, "y": 1.0000009}
    normalized = normalize(data, float_ndigits=6)
    assert normalized == {"x": 1.0, "y": 1.000001}


def test_normalize_recurses_into_nested_structures():
    data = {"a": [{"created_at": "x", "b": 1.23456789}]}
    assert normalize(data) == {"a": [{"b": 1.234568}]}


def test_canonical_json_sorts_keys():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_hash_mapping_ignores_key_order():
    assert hash_mapping({"a": 1, "b": 2}) == hash_mapping({"b": 2, "a": 1})


def test_hash_mapping_ignores_volatile_fields():
    a = {"created_at": "2024-01-01", "value": 1}
    b = {"created_at": "2099-12-31", "value": 1}
    assert hash_mapping(a) == hash_mapping(b)


def test_hash_file_is_stable_for_identical_content(tmp_path: Path):
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("hello world")
    file_b.write_text("hello world")
    assert hash_file(file_a) == hash_file(file_b)


def test_hash_file_differs_for_different_content(tmp_path: Path):
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("hello world")
    file_b.write_text("goodbye world")
    assert hash_file(file_a) != hash_file(file_b)


def _sample_mesh_report(**overrides) -> MeshReport:
    defaults = dict(
        input_path=Path("part.stl"),
        input_sha256="abc123",
        manifold=True,
        watertight=True,
        self_intersecting=False,
        self_intersection_count=0,
        shell_count=1,
        bbox=BBox(min=(0.0, 0.0, 0.0), max=(10.0, 10.0, 10.0)),
        surface_area_mm2=600.0,
        volume_mm3=1000.0,
    )
    defaults.update(overrides)
    return MeshReport(**defaults)


def test_hash_artifact_is_stable_across_equivalent_paths():
    """Two artifacts that only differ in *where* the input file lives on disk
    must hash identically -- input_path is excluded from the reproducibility
    hash so it's comparable across machines/clone locations."""
    a = _sample_mesh_report(input_path=Path("/home/alice/repo/part.stl"))
    b = _sample_mesh_report(input_path=Path("/Users/bob/dev/repo/part.stl"))
    assert hash_artifact(a) == hash_artifact(b)


def test_hash_artifact_changes_when_metrics_change():
    a = _sample_mesh_report(volume_mm3=1000.0)
    b = _sample_mesh_report(volume_mm3=1234.0)
    assert hash_artifact(a) != hash_artifact(b)


def test_hash_artifact_ignores_harmless_float_noise():
    a = _sample_mesh_report(volume_mm3=1000.0000001)
    b = _sample_mesh_report(volume_mm3=1000.0000002)
    assert hash_artifact(a) == hash_artifact(b)
