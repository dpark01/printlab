"""Round-trip and JSON-Schema-generation tests for every artifact model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from printlab.schemas import ARTIFACT_MODELS, SCHEMA_VERSION, BBox, MeshReport, Status

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"


def test_every_artifact_model_has_schema_version_field():
    for model_cls in ARTIFACT_MODELS:
        assert "schema_version" in model_cls.model_fields


def test_committed_json_schemas_are_up_to_date():
    """Guards against editing an artifact model without re-running
    scripts/generate_schemas.py -- agents read docs/schemas/*.json directly,
    so it must never silently drift from the actual Pydantic models."""
    for model_cls in ARTIFACT_MODELS:
        schema_path = SCHEMAS_DIR / f"{model_cls.__name__}.json"
        assert schema_path.is_file(), f"missing {schema_path}; run scripts/generate_schemas.py"
        committed = json.loads(schema_path.read_text())
        current = model_cls.model_json_schema()
        assert committed == current, f"{schema_path} is stale -- re-run scripts/generate_schemas.py"


def test_every_artifact_model_generates_json_schema():
    for model_cls in ARTIFACT_MODELS:
        schema = model_cls.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


def _sample_mesh_report() -> MeshReport:
    return MeshReport(
        input_path="part.stl",
        input_sha256="abc",
        manifold=True,
        watertight=True,
        self_intersecting=False,
        self_intersection_count=0,
        shell_count=1,
        bbox=BBox(min=(0, 0, 0), max=(1, 1, 1)),
        surface_area_mm2=6.0,
        volume_mm3=1.0,
    )


def test_mesh_report_round_trips_through_json():
    report = _sample_mesh_report()
    restored = MeshReport.model_validate_json(report.model_dump_json())
    assert restored == report


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        MeshReport(
            **_sample_mesh_report().model_dump(),
            unexpected_field="nope",
        )


def test_default_status_is_ok():
    report = _sample_mesh_report()
    assert report.status is Status.OK
    assert report.schema_version == SCHEMA_VERSION
