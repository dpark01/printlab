"""G-code analysis artifact: printlab.gcode.analyze() -> gcode_report.json.

This is the *authoritative* source of slicing metrics for every backend.
PrintLab never trusts a slicer's self-reported stats (observed empirically:
Bambu Studio CLI's own result JSON reported `layer_height: 0.0`,
`wall_loops: 0`, `sparse_infill_density: 0.0` on a real slice). Instead every
backend's raw G-code is parsed by printlab.gcode, and filament mass is always
computed by PrintLab from the material profile's density rather than scraped
from the slicer.
"""

from __future__ import annotations

from printlab.schemas.common import PrintLabArtifact


class GCodeReport(PrintLabArtifact):
    source_backend: str
    gcode_sha256: str

    layer_count: int
    layer_height_mm: float | None = None
    first_layer_height_mm: float | None = None

    filament_length_mm: float
    filament_volume_mm3: float
    filament_mass_g: float
    material_density_g_cm3: float

    estimated_time_s: float
