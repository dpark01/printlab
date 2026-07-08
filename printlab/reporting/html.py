"""HTML reporting: a secondary, human-facing rendering of the same data as
printlab.reporting.markdown -- self-contained (inline CSS, no external
requests) so the output directory stays a portable, offline-viewable bundle.
"""

from __future__ import annotations

import html as html_lib

from printlab.schemas import GCodeReport, MeshReport, PrintabilityReport, RunManifest, SliceResult, Status

_STATUS_LABEL = {Status.OK: "PASS", Status.WARNING: "WARN", Status.ERROR: "FAIL"}
_STATUS_CLASS = {Status.OK: "status-ok", Status.WARNING: "status-warning", Status.ERROR: "status-error"}

_STYLE = """
body { font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 760px;
       margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; }
table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: 0.3rem 0.6rem; border-bottom: 1px solid #eee; }
code { background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 3px; }
.status-ok { color: #1a7f37; font-weight: bold; }
.status-warning { color: #9a6700; font-weight: bold; }
.status-error { color: #cf222e; font-weight: bold; }
.advisory { color: #666; font-size: 0.9em; }
"""


def _escape(value: object) -> str:
    return html_lib.escape(str(value))


def render(
    *,
    part_name: str,
    mesh: MeshReport,
    slice_result: SliceResult | None,
    gcode: GCodeReport | None,
    printability: PrintabilityReport,
    manifest: RunManifest,
) -> str:
    # slice_result/gcode are None for printlab check (see pipeline.run_check):
    # slicing was skipped entirely, not merely failed.
    dims = tuple(mesh.bbox.max[i] - mesh.bbox.min[i] for i in range(3))
    overall_class = _STATUS_CLASS[printability.status]
    overall_label = _STATUS_LABEL[printability.status]

    backend_line = (
        f"<code>{_escape(slice_result.backend)} {_escape(slice_result.backend_version)}</code>"
        if slice_result
        else "<code>none (slicing skipped)</code>"
    )

    if gcode:
        slicing_rows = f"""<tr><td>Layers</td>
<td>{gcode.layer_count} (layer height: {gcode.layer_height_mm} mm)</td></tr>
<tr><td>Filament</td><td>{gcode.filament_length_mm:.1f} mm / {gcode.filament_mass_g:.2f} g</td></tr>
<tr><td>Estimated print time</td><td>{gcode.estimated_time_s / 60:.1f} min
<span class="advisory">(advisory &mdash; parsed from the slicer's own estimate,
not independently computed)</span></td></tr>"""
    else:
        slicing_rows = (
            '<tr><td colspan="2" class="advisory">Skipped (no slicer run) -- '
            "filament/time metrics unavailable; checks below cover geometry only.</td></tr>"
        )

    resolved_settings_hash = (
        _escape(slice_result.resolved_settings_sha256 or "n/a") if slice_result else "n/a"
    )

    checks_rows = "\n".join(
        f"<tr><td class='{_STATUS_CLASS[check.status]}'>{_STATUS_LABEL[check.status]}</td>"
        f"<td><code>{_escape(check.name)}</code></td><td>{_escape(check.message)}</td></tr>"
        for check in printability.checks
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PrintLab Report: {_escape(part_name)}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>PrintLab Report: {_escape(part_name)}</h1>
<p>Backend: {backend_line}
&mdash; Overall status: <span class="{overall_class}">{overall_label}</span>
&mdash; Provisional score: <b>{printability.provisional_score}/100</b>
<span class="advisory">(UNCALIBRATED &mdash; triage only, do not optimize)</span></p>

<h2>Geometry</h2>
<table>
<tr><td>Manifold / watertight</td><td>{mesh.manifold} / {mesh.watertight}</td></tr>
<tr><td>Dimensions</td><td>{dims[0]:.1f} &times; {dims[1]:.1f} &times; {dims[2]:.1f} mm</td></tr>
<tr><td>Volume</td><td>{mesh.volume_mm3:.2f} mm&sup3;</td></tr>
<tr><td>Surface area</td><td>{mesh.surface_area_mm2:.2f} mm&sup2;</td></tr>
</table>

<h2>Slicing</h2>
<table>
{slicing_rows}
</table>

<h2>Printability Checks</h2>
<table>
{checks_rows}
</table>

<h2>Provenance</h2>
<table>
<tr><td>PrintLab version</td><td><code>{_escape(manifest.printlab_version)}</code></td></tr>
<tr><td>Git commit</td><td><code>{_escape(manifest.git_commit or "n/a")}</code></td></tr>
<tr><td>Slicer resolved-settings hash</td>
<td><code>{resolved_settings_hash}</code></td></tr>
<tr><td>Run content hash</td><td><code>{_escape(manifest.content_hash or "n/a")}</code></td></tr>
</table>
</body>
</html>
"""
