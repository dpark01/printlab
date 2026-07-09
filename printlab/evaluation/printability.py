"""Printability evaluation: combine MeshReport + GCodeReport + printer
constraints into independent pass/warning/fail checks.

The independent `checks` (and raw `metrics`) are the real output an agent
reasons about. A `provisional_score` is also computed here, but it is an
explicitly UNCALIBRATED placeholder (see `printlab.schemas.evaluation`
docstring and `_compute_provisional_score` below): a fixed, arbitrary
per-check penalty for rough human triage only. It must not be optimized, and
`score_calibrated` stays `False` until weights come from real print outcomes.
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

# Arbitrary, uncalibrated placeholder penalties: a flat per-check deduction,
# deliberately NOT per-metric weights (those are exactly what would need real
# calibration data to justify -- a flat penalty is more honest about being
# provisional). See printlab.schemas.evaluation docstring: do not optimize the
# resulting score; it is triage-only until score_calibrated flips to True.
ERROR_PENALTY = 40  # arbitrary placeholder, uncalibrated
WARNING_PENALTY = 10  # arbitrary placeholder, uncalibrated


def _compute_provisional_score(checks: list[PrintabilityCheck]) -> int:
    # Uniform across the slicer/no-slicer paths on purpose: `printlab check`
    # (gcode=None) degrades layer_height_allowed to WARNING, so a healthy part
    # scores 90 via `check` vs. 100 via `all`. We do NOT special-case that to
    # make the score slicer-invariant -- simplicity is more honest for a number
    # already labeled a placeholder.
    score = 100
    for c in checks:
        if c.status is Status.ERROR:
            score -= ERROR_PENALTY
        elif c.status is Status.WARNING:
            score -= WARNING_PENALTY
    return max(0, score)


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


def _check_layer_height_allowed(gcode: GCodeReport | None, printer: PrinterProfile) -> PrintabilityCheck:
    if gcode is None or gcode.layer_height_mm is None:
        return PrintabilityCheck(
            name="layer_height_allowed",
            status=Status.WARNING,
            message=(
                "Layer height unknown: no G-code available (slicing was skipped)."
                if gcode is None
                else "Layer height could not be determined from G-code."
            ),
        )
    # 1 micron: real slicer G-code carries floating point noise across
    # hundreds of layers (observed directly: PrusaSlicer height comments
    # ranging 0.199997-0.200001 for a nominal 0.2mm layer height in one
    # file) -- 1e-6mm would be sub-nanometer precision, meaningless here.
    allowed = printer.allowed_layer_heights_mm
    ok = any(abs(gcode.layer_height_mm - h) < 1e-3 for h in allowed)
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


def _check_min_wall_thickness(mesh: MeshReport, printer: PrinterProfile) -> PrintabilityCheck:
    # WARNING, not ERROR, on either branch: this is a documented
    # approximation (see printlab.mesh.wall_thickness), not an exact
    # measurement, so it shouldn't be treated as certain as e.g. the
    # manifold/build-volume checks.
    if mesh.min_wall_thickness_mm is None:
        return PrintabilityCheck(
            name="min_wall_thickness",
            status=Status.WARNING,
            message="Wall thickness could not be estimated (ray casting produced no usable samples).",
        )
    ok = mesh.min_wall_thickness_mm >= printer.min_feature_size_mm
    location_suffix = (
        f" Thin region centered near {mesh.min_wall_thickness_location} (part-native coordinates)."
        if mesh.min_wall_thickness_location is not None
        else ""
    )
    return PrintabilityCheck(
        name="min_wall_thickness",
        status=Status.OK if ok else Status.WARNING,
        message=(
            f"Estimated wall thickness {mesh.min_wall_thickness_mm:.2f}mm meets "
            f"{printer.name}'s {printer.min_feature_size_mm}mm minimum feature size."
            if ok
            else f"Estimated wall thickness {mesh.min_wall_thickness_mm:.2f}mm is below "
            f"{printer.name}'s {printer.min_feature_size_mm}mm minimum feature size "
            "(5th-percentile of per-face ray-cast readings, not a strict minimum -- "
            "can overestimate true worst-case thickness near sharp edges)."
            f"{location_suffix}"
        ),
        metric_value=mesh.min_wall_thickness_mm,
        threshold=printer.min_feature_size_mm,
    )


def evaluate(mesh: MeshReport, gcode: GCodeReport | None, printer: PrinterProfile) -> PrintabilityReport:
    """`gcode` is `None` when slicing was skipped (see `printlab check` /
    `printlab.pipeline.run_check`): every mesh-derived check below still
    runs, and the gcode-derived checks/metrics degrade to unknown rather
    than failing outright.
    """
    checks = [
        _check_manifold(mesh),
        _check_self_intersection(mesh),
        _check_build_volume_fit(mesh, printer),
        _check_layer_height_allowed(gcode, printer),
        _check_min_wall_thickness(mesh, printer),
    ]

    metrics: dict[str, float | int | bool | str | None] = {
        "volume_mm3": mesh.volume_mm3,
        "surface_area_mm2": mesh.surface_area_mm2,
        "shell_count": mesh.shell_count,
        "overhang_area_mm2": mesh.overhang_area_mm2,
        "min_wall_thickness_mm": mesh.min_wall_thickness_mm,
        "max_unsupported_span_mm": mesh.max_unsupported_span_mm,
        "layer_count": gcode.layer_count if gcode else None,
        "filament_length_mm": gcode.filament_length_mm if gcode else None,
        "filament_mass_g": gcode.filament_mass_g if gcode else None,
        "estimated_time_s": gcode.estimated_time_s if gcode else None,
    }

    overall_status = Status.OK
    if any(check.status is Status.ERROR for check in checks):
        overall_status = Status.ERROR
    elif any(check.status is Status.WARNING for check in checks):
        overall_status = Status.WARNING

    return PrintabilityReport(
        metrics=metrics,
        checks=checks,
        status=overall_status,
        provisional_score=_compute_provisional_score(checks),
        score_calibrated=False,
    )
