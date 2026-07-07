"""Slicer-independent request/result contracts.

`SliceRequest` deliberately stays a *small allowlist* of overridable knobs
(the doc's original flat bag of every possible slicer setting was a leaky
abstraction). Everything else a slicer needs comes from the printer/material/
process profiles' native config bundles (see printlab.schemas.profiles) —
PrintLab does not attempt to model every native slicer setting.

`SliceResult` does not carry a `metrics: dict` grab-bag. Metrics are always
derived downstream by printlab.gcode from the emitted G-code, never trusted
from the slicer's own self-reported numbers (Bambu Studio's CLI has been
observed to emit zeroed metrics — see docs/environment.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import SCHEMA_VERSION, PrintLabArtifact


class SliceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION

    input_model: Path
    output_dir: Path

    printer_profile: Path
    material_profile: Path
    process_profile: Path | None = None

    # Small, explicit override allowlist. Backends map these to native keys;
    # anything not listed here belongs in a native config bundle, not in code.
    quality_preset: str | None = None
    supports: bool | None = None
    brim: bool | None = None
    infill_percent: float | None = None
    layer_height_mm: float | None = None


class Capabilities(BaseModel):
    """What a slicer backend can and can't do, so the pipeline can degrade gracefully."""

    model_config = ConfigDict(extra="forbid")

    backend: str
    available: bool
    version: str | None = None
    deterministic: bool = False
    emits_reliable_gcode_stats: bool = False
    supports_bambu_machines: bool = False
    supports_orientation: bool = False
    supports_supports: bool = True
    notes: str = ""


class SliceResult(PrintLabArtifact):
    model_config = ConfigDict(extra="forbid")

    backend: str
    backend_version: str

    gcode_path: Path | None = None
    project_path: Path | None = None

    # SHA-256 of the fully-resolved native settings actually handed to the
    # slicer binary (native bundle -> process profile -> CLI override,
    # applied in that precedence order). Recorded so provenance can prove
    # *which* settings produced this result even if resolution logic changes.
    resolved_settings_sha256: str | None = None
    resolved_settings: dict[str, Any] = Field(default_factory=dict)

    warnings: list[str] = Field(default_factory=list)
