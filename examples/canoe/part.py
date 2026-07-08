"""A small decorative canoe: a hollow, double-pointed hull with three flush
thwarts and a recessed "56" engraved into the solid bow deck.

This is the only file in this example an agent (or a human) should edit —
`build()` is CAD source; everything else in an output/ directory is a
generated artifact (see AGENTS.md).

The hull is built as three independent lofts of tapered ellipse stations
(bow cap, mid section, stern cap), each with its top half sliced off by a
plane cut to form the flat deck. Only the mid section is hollowed, via
`Workplane.shell()`, which is what gives it a genuinely uniform wall
thickness (rather than tapering off wall thickness by hand). The bow/stern
caps stay solid — which is also where the bow deck has enough flat area to
engrave the hull number.

Building the mid section as its own loft (instead of trimming it out of one
loft spanning the whole length) matters: a trimmed face still carries the
full loft's underlying surface, which is singular at the pointed tips, and
`shell()` fails there even though the visible trimmed region is nowhere
near a tip.
"""

from __future__ import annotations

import math

import cadquery as cq
from cadquery import Vector

# All dimensions in millimeters.
LENGTH = 75.0
OUTER_WIDTH = 14.0  # beam (max width), amidships
OUTER_DEPTH = 8.0  # hull depth, keel to gunwale, amidships
HULL_POWER = 0.55  # <1 keeps the hull full for longer before tapering to the tip
MIN_TIP = 0.35  # floor on station half-width/depth so end stations stay valid, non-degenerate wires

WALL = 1.2  # uniform hull wall thickness, enforced by shell() rather than hand-tapered

CAV_T0 = 0.16  # the mid (hollow) section spans this middle portion of the length;
CAV_T1 = 0.84  # outside it, the hull is a solid bow/stern cap

STATIONS_BOW = 9
STATIONS_MID = 25
STATIONS_STERN = 9

BOW_TEXT = "56"
BOW_TEXT_SIZE = 5.0
BOW_TEXT_DEPTH = 1.0
BOW_TEXT_X = 8.2  # within the solid bow deck (ends at CAV_T0 * LENGTH = 12mm), clear of the tip

THWART_STATIONS = (0.32, 0.5, 0.68)
THWART_LENGTH_X = 2.4
THWART_TOP_Z = 0.0  # flush with the deck/gunwale, not raised above it
THWART_BOTTOM_Z = -1.6
THWART_INSET = 0.4  # embed the thwart ends inside the outer surface for a clean fuse


def _outer_profile(t: float) -> tuple[float, float]:
    """Half-width and half-depth of the outer hull at station t in [0, 1] (0=bow, 1=stern)."""
    scale = math.sin(math.pi * t) ** HULL_POWER if 0 < t < 1 else 0.0
    half_width = max(MIN_TIP, (OUTER_WIDTH / 2) * scale)
    half_depth = max(MIN_TIP, OUTER_DEPTH * scale)
    return half_width, half_depth


def _local_half_width(t: float, z: float) -> float:
    """Half-width of the outer hull's elliptical cross-section at station t, at height z.

    Used to size the thwarts: the ellipse narrows away from z=0, so a thwart's Y-extent
    must be checked at its *lowest* z, not just at the top, or it pokes through the sides.
    """
    half_width, half_depth = _outer_profile(t)
    if half_depth <= abs(z):
        return 0.0
    return half_width * math.sqrt(1 - (z / half_depth) ** 2)


def _ellipse_wire(x: float, half_width: float, half_depth: float, n: int = 32) -> cq.Wire:
    """A closed elliptical wire at length position x, in the plane normal to the hull's long axis."""
    pts = [
        (half_width * math.cos(2 * math.pi * i / n), half_depth * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    wire = cq.Workplane("YZ").moveTo(*pts[0]).polyline(pts[1:]).close().val()
    return wire.translate(Vector(x, 0, 0))


def _half_hull_piece(t0: float, t1: float, n_stations: int) -> cq.Shape:
    """A solid loft between t0 and t1, sliced to keep only the lower half (z <= 0) of each
    elliptical station — a rounded keel under a flat deck, without the loft ever having to
    represent that flat/curved seam directly (which is what made shell() unreliable)."""
    wires = []
    for i in range(n_stations):
        t = t0 + (t1 - t0) * i / (n_stations - 1)
        half_width, half_depth = _outer_profile(t)
        wires.append(_ellipse_wire(t * LENGTH, half_width, half_depth))
    loft = cq.Solid.makeLoft(wires, ruled=False)
    top_half = cq.Solid.makeBox(LENGTH + 10, 40, 40, pnt=Vector(-5, -20, 0))
    return loft.cut(top_half)


def _build_hull() -> cq.Shape:
    bow_cap = _half_hull_piece(0.0, CAV_T0, STATIONS_BOW)
    mid = _half_hull_piece(CAV_T0, CAV_T1, STATIONS_MID)
    stern_cap = _half_hull_piece(CAV_T1, 1.0, STATIONS_STERN)
    mid_shell = cq.Workplane(obj=mid).faces(">Z").shell(-WALL, kind="intersection").val()
    return bow_cap.fuse(mid_shell).fuse(stern_cap)


def _add_thwarts(hull: cq.Shape) -> cq.Shape:
    for t in THWART_STATIONS:
        x = t * LENGTH
        half_width = _local_half_width(t, THWART_BOTTOM_Z) - THWART_INSET
        box = cq.Solid.makeBox(
            THWART_LENGTH_X,
            2 * half_width,
            THWART_TOP_Z - THWART_BOTTOM_Z,
            pnt=Vector(x - THWART_LENGTH_X / 2, -half_width, THWART_BOTTOM_Z),
        )
        hull = hull.fuse(box)
    return hull


def _bow_text_cutter() -> cq.Shape:
    plane = cq.Plane(origin=(BOW_TEXT_X, 0, 0), normal=(0, 0, 1), xDir=(1, 0, 0))
    return cq.Compound.makeText(
        BOW_TEXT,
        BOW_TEXT_SIZE,
        -BOW_TEXT_DEPTH,
        font="Arial",
        kind="bold",
        halign="center",
        valign="center",
        position=plane,
    )


def build() -> cq.Workplane:
    """Build the canoe and return it as a single-solid cadquery.Workplane."""
    hull = _build_hull()
    hull = _add_thwarts(hull)
    hull = hull.cut(_bow_text_cutter())
    return cq.Workplane(obj=hull)
