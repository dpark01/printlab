"""Markdown reporting: a secondary, human-facing rendering of the same data.

Structured JSON artifacts are the primary interface agents consume; this
report exists for humans skimming a run's outcome (SETUP.md: "Markdown and
HTML reports are secondary human-facing outputs").
"""

from __future__ import annotations

from printlab.schemas import GCodeReport, MeshReport, PrintabilityReport, RunManifest, SliceResult, Status

_STATUS_LABEL = {Status.OK: "PASS", Status.WARNING: "WARN", Status.ERROR: "FAIL"}


def render(
    *,
    part_name: str,
    mesh: MeshReport,
    slice_result: SliceResult,
    gcode: GCodeReport,
    printability: PrintabilityReport,
    manifest: RunManifest,
) -> str:
    dims = tuple(mesh.bbox.max[i] - mesh.bbox.min[i] for i in range(3))
    lines = [
        f"# PrintLab Report: {part_name}",
        "",
        f"- Backend: **{slice_result.backend} {slice_result.backend_version}**",
        f"- Overall status: **{_STATUS_LABEL[printability.status]}**",
        "",
        "## Geometry",
        "",
        f"- Manifold / watertight: {mesh.manifold} / {mesh.watertight}",
        f"- Dimensions: {dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm",
        f"- Volume: {mesh.volume_mm3:.2f} mm³",
        f"- Surface area: {mesh.surface_area_mm2:.2f} mm²",
        "",
        "## Slicing",
        "",
        f"- Layers: {gcode.layer_count} (layer height: {gcode.layer_height_mm} mm)",
        f"- Filament: {gcode.filament_length_mm:.1f} mm / {gcode.filament_mass_g:.2f} g",
        f"- Estimated print time: {gcode.estimated_time_s / 60:.1f} min "
        "(advisory -- parsed from the slicer's own estimate, not independently computed)",
        "",
        "## Printability Checks",
        "",
    ]
    for check in printability.checks:
        lines.append(f"- [{_STATUS_LABEL[check.status]}] **{check.name}** -- {check.message}")
    lines += [
        "",
        "## Provenance",
        "",
        f"- PrintLab version: {manifest.printlab_version}",
        f"- Git commit: {manifest.git_commit or 'n/a'}",
        f"- Slicer resolved-settings hash: {slice_result.resolved_settings_sha256 or 'n/a'}",
        f"- Run content hash: {manifest.content_hash or 'n/a'}",
        "",
    ]
    return "\n".join(lines)
