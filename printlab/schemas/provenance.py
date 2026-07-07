"""Run manifest: the artifact that makes a PrintLab run auditable.

This is the piece SETUP.md's design omitted entirely. It is the backbone of
both the Tier-1 reproducibility contract (see printlab.determinism) and of an
agent loop's ability to answer "why did the metrics change between run A and
run B?" by diffing two manifests.

`created_at` is recorded for humans but is intentionally excluded from any
reproducibility hash (see printlab.determinism.VOLATILE_KEYS) — it is wall
clock, not engineering state.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import SCHEMA_VERSION


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION

    printlab_version: str
    git_commit: str | None = None
    platform: str
    created_at: str

    # Every tool whose output affects reproducibility: printlab itself,
    # cadquery/cadquery-ocp (OCCT), trimesh, the slicer binary + version, etc.
    tool_versions: dict[str, str] = Field(default_factory=dict)

    # SHA-256 of each named input: CAD source, each resolved profile file,
    # each native config bundle actually used.
    input_hashes: dict[str, str] = Field(default_factory=dict)
    profile_hashes: dict[str, str] = Field(default_factory=dict)

    # SHA-256 of the fully-resolved settings dict handed to the slicer,
    # matching SliceResult.resolved_settings_sha256 for cross-checking.
    resolved_settings_hash: str | None = None

    # Filled in once all stage artifacts exist: artifact name -> content hash
    # (see printlab.determinism.hash_artifact), plus an overall content hash.
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    content_hash: str | None = None

    extra: dict[str, Any] = Field(default_factory=dict)
