"""Profile loading and resolution.

Loading is just YAML -> Pydantic. The interesting part is resolution
precedence for the small allowlist of overridable process knobs (layer
height, infill, supports, brim, wall count): **native bundle -> process
profile -> explicit SliceRequest override**, applied in that order so a
caller's explicit choice always wins, the process profile's own defaults
apply next, and the committed native bundle file is the base every backend
starts from. `resolve_process_overrides()` returns the effective values *and*
which layer supplied each one, so provenance can record not just the value
but why it was chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from printlab.schemas import MaterialProfile, PrinterProfile, ProcessProfile, SliceRequest


def load_printer_profile(path: Path) -> PrinterProfile:
    return PrinterProfile.model_validate(_load_yaml(path))


def load_material_profile(path: Path) -> MaterialProfile:
    return MaterialProfile.model_validate(_load_yaml(path))


def load_process_profile(path: Path) -> ProcessProfile:
    return ProcessProfile.model_validate(_load_yaml(path))


def _load_yaml(path: Path) -> dict[str, Any]:
    with Path(path).open("r") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class ResolvedOverride:
    value: Any
    source: str  # "request" | "process_profile"


@dataclass(frozen=True)
class ResolvedProcessSettings:
    layer_height_mm: ResolvedOverride
    infill_percent: ResolvedOverride
    supports: ResolvedOverride
    brim: ResolvedOverride
    wall_count: ResolvedOverride

    def as_dict(self) -> dict[str, Any]:
        """Effective values only, suitable for hashing into provenance."""
        return {
            "layer_height_mm": self.layer_height_mm.value,
            "infill_percent": self.infill_percent.value,
            "supports": self.supports.value,
            "brim": self.brim.value,
            "wall_count": self.wall_count.value,
        }


def resolve_process_overrides(request: SliceRequest, process: ProcessProfile) -> ResolvedProcessSettings:
    """Apply the process-profile -> CLI-override precedence for the knob allowlist.

    The native config bundle is the implicit base layer underneath this: each
    backend loads it first, then applies these resolved values on top.
    `wall_count` may resolve to None (neither request nor profile set it) --
    backends must treat that as "no override, use the native bundle's own
    default" rather than passing a literal None through to a CLI flag.
    """

    def resolve(request_value: Any, profile_value: Any) -> ResolvedOverride:
        if request_value is not None:
            return ResolvedOverride(value=request_value, source="request")
        return ResolvedOverride(value=profile_value, source="process_profile")

    return ResolvedProcessSettings(
        layer_height_mm=resolve(request.layer_height_mm, process.layer_height_mm),
        infill_percent=resolve(request.infill_percent, process.infill_percent),
        supports=resolve(request.supports, process.supports),
        brim=resolve(request.brim, process.brim),
        wall_count=resolve(request.wall_count, process.wall_count),
    )
