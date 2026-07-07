"""Low-level G-code parsing: extract layer/extrusion/time facts from raw text.

PrintLab derives filament length and layer count itself, directly from motion
commands, for every backend — never from a slicer's self-reported numbers
(observed empirically: Bambu Studio's own `result.json` side-channel reports
`total_used_g: 0.0` and `filament_density: 0` on a real slice; even its
G-code header's `total filament weight [g]` comment is `0.00`). This is what
makes two different slicers' output comparable through one abstraction.

The one exception is **print time**: simulating firmware motion planning
(acceleration/jerk/junction deviation) to derive a true independent time
estimate is a hard, deferred problem (Phase 2+, alongside overhangs/min-wall
— see SETUP.md deviations). `estimated_time_s` is parsed from the slicer's
own comment and should be treated as advisory, unlike every other field this
module computes.

Layer-change and per-layer-height comment conventions differ by slicer
lineage:
  - PrusaSlicer / OrcaSlicer: ``;LAYER_CHANGE`` then ``;HEIGHT:<mm>``
  - Bambu Studio:             ``; CHANGE_LAYER`` then ``; LAYER_HEIGHT: <mm>``
Both are handled below; an unrecognized slicer's G-code would simply report
layer_count=0 rather than raising, since PrintLab must never crash on a
third-party artifact it doesn't own the format of.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_LAYER_CHANGE_MARKERS = {"LAYER_CHANGE", "CHANGE_LAYER"}

# Matches ";HEIGHT:0.2" (PrusaSlicer/Orca) or "; LAYER_HEIGHT: 0.2" (Bambu),
# but not ";Z_HEIGHT: 0.2" / ";Z:0.2" (absolute Z, not layer thickness).
_LAYER_HEIGHT_RE = re.compile(r"^;\s*(?:LAYER_)?HEIGHT\s*:\s*([0-9.]+)\s*$")

_E_PARAM_RE = re.compile(r"[Ee](-?[0-9]*\.?[0-9]+)")

_DURATION_PATTERNS = (
    re.compile(r"total estimated time\s*:\s*([0-9dhms .]+)", re.IGNORECASE),
    re.compile(r"estimated printing time \(normal mode\)\s*=\s*([0-9dhms .]+)", re.IGNORECASE),
)

_DURATION_COMPONENT_RE = re.compile(
    r"(?:(?P<days>\d+)d)?\s*(?:(?P<hours>\d+)h)?\s*(?:(?P<minutes>\d+)m)?\s*(?:(?P<seconds>\d+)s)?"
)


@dataclass
class ParsedGcode:
    layer_count: int = 0
    first_layer_height_mm: float | None = None
    layer_height_mm: float | None = None
    filament_length_mm: float = 0.0
    estimated_time_s: float | None = None
    layer_heights_seen: list[float] = field(default_factory=list, repr=False)


def _parse_duration_to_seconds(text: str) -> float | None:
    match = _DURATION_COMPONENT_RE.search(text)
    if not match or not any(match.groups()):
        return None
    parts = {key: int(value) if value else 0 for key, value in match.groupdict().items()}
    return float(parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"])


def _extract_estimated_time_s(text: str) -> float | None:
    for pattern in _DURATION_PATTERNS:
        match = pattern.search(text)
        if match:
            seconds = _parse_duration_to_seconds(match.group(1))
            if seconds is not None:
                return seconds
    return None


def _mode_or_first(values: list[float]) -> float | None:
    if not values:
        return None
    counts: dict[float, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts.items(), key=lambda item: (item[1], -values.index(item[0])))[0]


def parse_gcode(text: str) -> ParsedGcode:
    """Parse raw G-code text into layer/extrusion/time facts.

    `text` is expected to be the full contents of a single-plate G-code file.
    Never raises on malformed input beyond what Python's own parsing needs;
    unrecognized lines are simply skipped.

    Filament length is computed as the peak of a reconstructed continuous
    "virtual E" position, not a naive sum of positive E deltas. Retract/
    un-retract (or "prime") cycles are extremely common (every travel move)
    and a naive positive-delta sum double counts each one: the un-retract
    merely returns the extruder to a position it already reached, so it must
    not add to the total. Tracking the running maximum of a continuous
    virtual E axis - reconstructed across G92 resets via a persistent offset
    in absolute mode, or accumulated directly in relative mode - nets these
    round trips out correctly in both extrusion modes.
    """
    absolute_extrusion = True
    raw_e = 0.0
    e_offset = 0.0
    virtual_e = 0.0
    max_virtual_e = 0.0
    layer_count = 0
    layer_heights: list[float] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith(";"):
            stripped_marker = line.lstrip(";").strip().upper()
            if stripped_marker in _LAYER_CHANGE_MARKERS:
                layer_count += 1
                continue
            height_match = _LAYER_HEIGHT_RE.match(line)
            if height_match:
                layer_heights.append(float(height_match.group(1)))
            continue

        code = line.split(None, 1)[0].upper() if line.split(None, 1) else ""

        if code == "M82":
            absolute_extrusion = True
            continue
        if code == "M83":
            absolute_extrusion = False
            continue
        if code == "G92":
            e_match = _E_PARAM_RE.search(line)
            if e_match:
                new_raw_e = float(e_match.group(1))
                if absolute_extrusion:
                    # Re-anchor the offset so the reconstructed virtual_e is
                    # unchanged by this purely-notational coordinate reset.
                    e_offset = virtual_e - new_raw_e
                    raw_e = new_raw_e
                else:
                    virtual_e = new_raw_e
            continue
        if code in ("G0", "G1"):
            e_match = _E_PARAM_RE.search(line)
            if not e_match:
                continue
            e_value = float(e_match.group(1))
            if absolute_extrusion:
                raw_e = e_value
                virtual_e = raw_e + e_offset
            else:
                virtual_e += e_value
            if virtual_e > max_virtual_e:
                max_virtual_e = virtual_e

    total_extruded_mm = max_virtual_e

    first_layer_height = layer_heights[0] if layer_heights else None
    layer_height = _mode_or_first(layer_heights[1:]) if len(layer_heights) > 1 else first_layer_height

    return ParsedGcode(
        layer_count=layer_count,
        first_layer_height_mm=first_layer_height,
        layer_height_mm=layer_height,
        filament_length_mm=total_extruded_mm,
        estimated_time_s=_extract_estimated_time_s(text),
        layer_heights_seen=layer_heights,
    )
