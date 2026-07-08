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

    # Transversely-isotropic linear-elastic constants for FEA (printlab.fea).
    # FDM/FFF parts are stiffer/stronger in-plane within a layer ("xy") than
    # through the layer stack ("z", the build direction), because interlayer
    # bonds are weaker than continuous extruded roads -- transverse isotropy
    # (in-plane isotropic, distinct through-thickness) is the standard first
    # approximation. "xy"/"z" are RELATIVE to whatever build direction an
    # analysis uses, not fixed world axes (printlab.fea orients the material
    # frame per-analysis via CalculiX's *ORIENTATION card).
    #
    # These are PLACEHOLDER literature values, not measured/calibrated for any
    # specific printer+filament+process -- exactly as provisional as anything
    # else this codebase flags uncalibrated (cf. PrintabilityReport's
    # provisional_score). Treat FEA output as order-of-magnitude, not
    # certification-grade, until a real coupon-test calibration replaces these.
    #
    # In-plane shear modulus G_xy is NOT stored: under transverse isotropy the
    # in-plane behavior is isotropic, so G_xy = E_xy / (2 * (1 + nu_xy))
    # exactly (printlab.fea.deck derives it). Only the out-of-plane
    # shear_modulus_xz_mpa needs its own field, since interlayer shear is a
    # known weak point that is not derivable from the in-plane constants.
    young_modulus_xy_mpa: float
    young_modulus_z_mpa: float
    poisson_ratio_xy: float
    poisson_ratio_xz: float
    shear_modulus_xz_mpa: float
    tensile_strength_xy_mpa: float
    tensile_strength_z_mpa: float

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
