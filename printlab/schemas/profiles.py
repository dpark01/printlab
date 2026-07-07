"""Profile schemas: the 3-part split instead of a universal slicer schema.

Rather than trying to abstract every slicer setting (a maintenance treadmill
no one wins), a profile is three things:

  (a) slicer-independent engineering constraints + material physics, typed
      below, usable with zero slicers installed (this is what makes most
      evaluation metrics deterministic and CI-testable without a binary);
  (b) a pointer to a version-controlled *native* config bundle per backend
      (PrusaSlicer .ini, Bambu machine/process/filament .json), committed
      under profiles/native/ and hashed into provenance rather than
      reimplemented;
  (c) a small allowlist of overridable knobs on ProcessProfile, mapped to
      native keys by each backend, with explicit resolution precedence:
      native bundle -> process profile -> CLI override (see
      printlab.profiles.resolver).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import SCHEMA_VERSION


class PrinterProfile(BaseModel):
    """(a) Engineering constraints for a physical machine."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    name: str
    manufacturer: str

    build_volume_mm: tuple[float, float, float]
    nozzle_diameter_mm: float
    allowed_layer_heights_mm: list[float]
    min_feature_size_mm: float
    max_bed_temp_c: float | None = None
    max_nozzle_temp_c: float | None = None

    # (b) backend name -> path to a committed native machine config bundle.
    native_bundle: dict[str, Path] = Field(default_factory=dict)


class MaterialProfile(BaseModel):
    """(a) Material physics needed to compute mass/temperature checks ourselves."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    name: str
    material: str  # e.g. "PLA", "PETG", "ABS"
    density_g_cm3: float
    nozzle_temp_c: tuple[float, float]  # (min, max)
    bed_temp_c: tuple[float, float]

    native_bundle: dict[str, Path] = Field(default_factory=dict)


class ProcessProfile(BaseModel):
    """(c) The small allowlist of overridable process knobs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    name: str
    layer_height_mm: float
    infill_percent: float
    supports: bool
    brim: bool
    wall_count: int | None = None

    native_bundle: dict[str, Path] = Field(default_factory=dict)
