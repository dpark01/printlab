"""Printability evaluation: combine MeshReport + GCodeReport + printer
constraints into independent pass/warning/fail checks.

Deliberately no composite 0-100 score in v0.1 (see printlab.schemas.evaluation
docstring): raw metrics plus independent checks are exposed instead, so an
agent reasons about specific failure modes rather than an uncalibrated
scalar.
"""

from __future__ import annotations

from printlab.schemas import (
    GCodeReport,
    MeshReport,
    PrintabilityCheck,
    PrintabilityReport,
    PrinterProfile,
    Status,
)


def _check_manifold(mesh: MeshReport) -> PrintabilityCheck:
    ok = mesh.manifold and mesh.watertight
    return PrintabilityCheck(
        name="manifold_watertight",
        status=Status.OK if ok else Status.ERROR,
        message=(
            "Mesh is manifold and watertight."
            if ok
            else "Mesh is not manifold/watertight; slicing may fail or produce holes."
        ),
        metric_value=ok,
    )


def _check_self_intersection(mesh: MeshReport) -> PrintabilityCheck:
    # See printlab.mesh.analyze docstring: this is a bounded bbox-overlap
    # heuristic, not exhaustive triangle-pair testing -- flagged as a
    # warning rather than a failure since it may have false positives.
    ok = not mesh.self_intersecting
    return PrintabilityCheck(
        name="self_intersection_heuristic",
        status=Status.OK if ok else Status.WARNING,
        message=(
            "No overlapping shells detected."
            if ok
            else f"{mesh.self_intersection_count} overlapping shell pair(s) detected "
            "(bbox heuristic, not exhaustive)."
        ),
        metric_value=mesh.self_intersection_count,
    )


def _check_build_volume_fit(mesh: MeshReport, printer: PrinterProfile) -> PrintabilityCheck:
    dims = tuple(mesh.bbox.max[i] - mesh.bbox.min[i] for i in range(3))
    fits = all(dims[i] <= printer.build_volume_mm[i] for i in range(3))
    dims_str = f"{dims[0]:.1f}x{dims[1]:.1f}x{dims[2]:.1f}mm"
    volume_str = "x".join(f"{v:.0f}" for v in printer.build_volume_mm) + "mm"
    return PrintabilityCheck(
        name="build_volume_fit",
        status=Status.OK if fits else Status.ERROR,
        message=(
            f"Part {dims_str} fits within {printer.name}'s {volume_str} build volume."
            if fits
            else f"Part {dims_str} exceeds {printer.name}'s {volume_str} build volume."
        ),
        metric_value=fits,
    )


def _check_layer_height_allowed(gcode: GCodeReport, printer: PrinterProfile) -> PrintabilityCheck:
    if gcode.layer_height_mm is None:
        return PrintabilityCheck(
            name="layer_height_allowed",
            status=Status.WARNING,
            message="Layer height could not be determined from G-code.",
        )
    allowed = printer.allowed_layer_heights_mm
    ok = any(abs(gcode.layer_height_mm - h) < 1e-6 for h in allowed)
    return PrintabilityCheck(
        name="layer_height_allowed",
        status=Status.OK if ok else Status.WARNING,
        message=(
            f"Layer height {gcode.layer_height_mm}mm is one of {printer.name}'s allowed heights."
            if ok
            else f"Layer height {gcode.layer_height_mm}mm is not in {printer.name}'s allowed set {allowed}."
        ),
        metric_value=gcode.layer_height_mm,
    )


def evaluate(mesh: MeshReport, gcode: GCodeReport, printer: PrinterProfile) -> PrintabilityReport:
    checks = [
        _check_manifold(mesh),
        _check_self_intersection(mesh),
        _check_build_volume_fit(mesh, printer),
        _check_layer_height_allowed(gcode, printer),
    ]

    metrics: dict[str, float | int | bool | str] = {
        "volume_mm3": mesh.volume_mm3,
        "surface_area_mm2": mesh.surface_area_mm2,
        "shell_count": mesh.shell_count,
        "layer_count": gcode.layer_count,
        "filament_length_mm": gcode.filament_length_mm,
        "filament_mass_g": gcode.filament_mass_g,
        "estimated_time_s": gcode.estimated_time_s,
    }

    overall_status = Status.OK
    if any(check.status is Status.ERROR for check in checks):
        overall_status = Status.ERROR
    elif any(check.status is Status.WARNING for check in checks):
        overall_status = Status.WARNING

    return PrintabilityReport(metrics=metrics, checks=checks, status=overall_status)
