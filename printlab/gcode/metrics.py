"""Build the authoritative GCodeReport from a slicer's raw G-code output.

Filament mass is always computed by PrintLab from the material profile's
density (see printlab.schemas.profiles.MaterialProfile), never scraped from a
slicer's own report -- both Bambu Studio's result.json side-channel and its
G-code header comment reported a filament weight of exactly 0.00g in
practice, which is the concrete evidence behind this design rule.
"""

from __future__ import annotations

import math
from pathlib import Path

from printlab.determinism import hash_file
from printlab.gcode.parser import parse_gcode
from printlab.schemas import ArtifactError, GCodeReport, Status

#: Standard desktop-FDM filament diameter. Not modeled as a profile field in
#: v0.1 since it is a near-universal constant; revisit if a non-1.75mm
#: printer profile is ever added.
DEFAULT_FILAMENT_DIAMETER_MM = 1.75


def analyze(
    gcode_path: Path,
    *,
    backend: str,
    material_density_g_cm3: float,
    filament_diameter_mm: float = DEFAULT_FILAMENT_DIAMETER_MM,
) -> GCodeReport:
    gcode_path = Path(gcode_path)
    gcode_sha256 = hash_file(gcode_path)

    try:
        text = gcode_path.read_text(errors="replace")
    except OSError as exc:
        return GCodeReport(
            source_backend=backend,
            gcode_sha256=gcode_sha256,
            layer_count=0,
            filament_length_mm=0.0,
            filament_volume_mm3=0.0,
            filament_mass_g=0.0,
            material_density_g_cm3=material_density_g_cm3,
            estimated_time_s=0.0,
            status=Status.ERROR,
            errors=[ArtifactError(code="gcode_read_failed", message=str(exc), stage="gcode")],
        )

    parsed = parse_gcode(text)

    filament_radius_mm = filament_diameter_mm / 2
    filament_volume_mm3 = parsed.filament_length_mm * math.pi * filament_radius_mm**2
    filament_mass_g = (filament_volume_mm3 / 1000.0) * material_density_g_cm3

    status = Status.OK
    errors: list[ArtifactError] = []
    if parsed.layer_count == 0:
        status = Status.WARNING
        errors.append(
            ArtifactError(
                code="no_layers_detected",
                message="No recognized layer-change markers found in G-code; layer_count may be unreliable.",
                stage="gcode",
            )
        )
    if parsed.estimated_time_s is None:
        status = Status.WARNING if status is Status.OK else status
        errors.append(
            ArtifactError(
                code="time_estimate_unavailable",
                message="Could not parse an estimated-print-time comment from this backend's G-code. "
                "Unlike every other field in this report, estimated_time_s is advisory, not computed "
                "independently -- see module docstring in printlab.gcode.parser.",
                stage="gcode",
            )
        )

    return GCodeReport(
        source_backend=backend,
        gcode_sha256=gcode_sha256,
        layer_count=parsed.layer_count,
        layer_height_mm=parsed.layer_height_mm,
        first_layer_height_mm=parsed.first_layer_height_mm,
        filament_length_mm=parsed.filament_length_mm,
        filament_volume_mm3=filament_volume_mm3,
        filament_mass_g=filament_mass_g,
        material_density_g_cm3=material_density_g_cm3,
        estimated_time_s=parsed.estimated_time_s or 0.0,
        status=status,
        errors=errors,
    )
