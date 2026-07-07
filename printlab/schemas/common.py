"""Shared primitives used by every artifact schema.

Every PrintLab artifact carries the same three things: a `schema_version` (so
an agent or a future PrintLab version can tell what shape it's reading), a
`status` (ok/warning/error), and a structured `errors` list. This is the
"uniform status + errors contract" called for in SETUP.md's gap analysis —
agents branch on these fields instead of scraping free-form text.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: Bumped whenever an artifact schema's shape changes in a way that could
#: break a consumer. Independent of printlab's own package version.
SCHEMA_VERSION = "0.1.0"


class Status(StrEnum):
    """Outcome of a stage, or of a single evaluation check."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class ArtifactError(BaseModel):
    """A single structured failure, so an agent can branch without parsing prose."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str
    context: dict[str, Any] = Field(default_factory=dict)


class PrintLabArtifact(BaseModel):
    """Base class for every artifact PrintLab writes to disk as JSON."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    status: Status = Status.OK
    errors: list[ArtifactError] = Field(default_factory=list)


class BBox(BaseModel):
    """Axis-aligned bounding box, in millimeters."""

    model_config = ConfigDict(extra="forbid")

    min: tuple[float, float, float]
    max: tuple[float, float, float]
