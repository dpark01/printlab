"""Structured result of compiling a CAD source file."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from printlab.schemas.common import PrintLabArtifact


class CadBuildReport(PrintLabArtifact):
    backend_name: str
    source_path: str
    step_path: str | None = None
    stl_path: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
