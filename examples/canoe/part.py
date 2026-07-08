"""A small decorative canoe: a hollow, double-pointed hull with three flush
thwarts, a recessed "56" on the bow deck, and "2026" / "MHA" engraved into
the port / starboard hull sides near the bow.

This is the only file in this example an agent (or a human) should edit —
`build()` is CAD source; everything else in an output/ directory is a
generated artifact (see AGENTS.md).

All shaping/placement below is done in a "natural" (display) frame: bow at
x=0, keel at the bottom (z<0), rim/deck at z=0 — i.e. the canoe sits the way
it would float. `build()` flips the finished solid 180 degrees about the
length axis as the very last step, so the file the slicer sees is rim-down
(flat side down on the bed, tapering smoothly up to the keel) rather than
keel-down (which has a steep, unsupported overhang right along the keel
line). Since it's a rotation and not a mirror, nothing about the model's
geometry — including the text — needs to be authored differently to
account for it; the physical print just needs to be flipped back over
after coming off the bed to sit right-side up.

The hull is built as three independent lofts of tapered superellipse
stations (bow cap, mid section, stern cap), each with its top half sliced
off by a plane cut to form the flat deck. Only the mid section is hollowed,
via `Workplane.shell()`, which is what gives it a genuinely uniform wall
thickness (rather than tapering off wall thickness by hand). The bow/stern
caps stay solid — which is also where the bow deck has enough flat area to
engrave the hull number. A superellipse (exponent > 2) is used instead of a
true ellipse so the sides run closer to vertical near the waterline, both
for a more hull-like profile and so the port/starboard text sits on a
surface that curves less steeply.

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
SHAPE_N = 3.0  # superellipse exponent for the cross-section: 2 = true ellipse, higher = more vertical sides

WALL = 1.2  # uniform hull wall thickness, enforced by shell() rather than hand-tapered

CAV_T0 = 0.16  # the mid (hollow) section spans this middle portion of the length;
CAV_T1 = 0.84  # outside it, the hull is a solid bow/stern cap

STATIONS_BOW = 9
STATIONS_MID = 25
STATIONS_STERN = 9

FLAT_KEEL_SHAVE = 1.0  # mm shaved off the very bottom of the hull so the display orientation sits flat

BOW_TEXT = "56"
BOW_TEXT_SIZE = 5.0
BOW_TEXT_DEPTH = 1.0
BOW_TEXT_X = 8.2  # within the solid bow deck (ends at CAV_T0 * LENGTH = 12mm), clear of the tip

THWART_STATIONS = (0.32, 0.5, 0.68)
THWART_LENGTH_X = 2.4
THWART_TOP_Z = 0.0  # flush with the deck/gunwale, not raised above it
THWART_BOTTOM_Z = -1.6
THWART_INSET = 0.4  # embed the thwart ends inside the outer surface for a clean fuse

SIDE_TEXT_PORT = "2026"
SIDE_TEXT_STARBOARD = "MHA"
SIDE_TEXT_SIZE = 3.0
SIDE_TEXT_DEPTH = 0.4  # shallow: the mid-section wall here is only WALL thick
SIDE_TEXT_X = 22.0  # near the bow, well into the thin-walled mid section
SIDE_TEXT_Z = -2.0  # below the gunwale (z=0), above the waterline-ish depth
SIDE_TEXT_OVERSHOOT = 0.15  # start the cut this far *outside* the analytic surface point, so
# it always crosses the small gap between the analytic curve and the actual faceted loft surface
# (skipping this left a sliver of un-cut skin over the recess -- a disconnected shell, not a warning)


def _outer_profile(t: float) -> tuple[float, float]:
    """Half-width and half-depth of the outer hull at station t in [0, 1] (0=bow, 1=stern)."""
    scale = math.sin(math.pi * t) ** HULL_POWER if 0 < t < 1 else 0.0
    half_width = max(MIN_TIP, (OUTER_WIDTH / 2) * scale)
    half_depth = max(MIN_TIP, OUTER_DEPTH * scale)
    return half_width, half_depth


def _local_half_width(t: float, z: float) -> float:
    """Half-width of the outer hull's superellipse cross-section at station t, at height z.

    Used to size the thwarts: the cross-section narrows away from z=0, so a thwart's
    Y-extent must be checked at its *lowest* z, not just at the top, or it pokes through
    the sides.
    """
    half_width, half_depth = _outer_profile(t)
    if half_depth <= abs(z):
        return 0.0
    return half_width * (1 - abs(z / half_depth) ** SHAPE_N) ** (1 / SHAPE_N)


def _surface_point_and_normal(t: float, phi: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Point and outward unit normal on the outer hull surface at station t, angle phi
    (phi=0 -> +Y/starboard, phi=pi -> -Y/port, phi=-pi/2 -> keel)."""
    half_width, half_depth = _outer_profile(t)
    c, s = math.cos(phi), math.sin(phi)
    y = half_width * math.copysign(abs(c) ** (2 / SHAPE_N), c)
    z = half_depth * math.copysign(abs(s) ** (2 / SHAPE_N), s)
    # Outward normal from the gradient of |y/half_width|^n + |z/half_depth|^n = 1.
    gy = (SHAPE_N / half_width) * math.copysign(abs(c) ** (SHAPE_N - 1), c) if c != 0 else 0.0
    gz = (SHAPE_N / half_depth) * math.copysign(abs(s) ** (SHAPE_N - 1), s) if s != 0 else 0.0
    mag = math.hypot(gy, gz)
    if mag < 1e-9:
        return (y, z), (0.0, 1.0)
    return (y, z), (gy / mag, gz / mag)


def _superellipse_wire(x: float, half_width: float, half_depth: float, n: int = 32) -> cq.Wire:
    """A closed superellipse wire at length position x, in the plane normal to the hull's long axis."""
    pts = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        c, s = math.cos(theta), math.sin(theta)
        y = half_width * math.copysign(abs(c) ** (2 / SHAPE_N), c)
        z = half_depth * math.copysign(abs(s) ** (2 / SHAPE_N), s)
        pts.append((y, z))
    wire = cq.Workplane("YZ").moveTo(*pts[0]).polyline(pts[1:]).close().val()
    return wire.translate(Vector(x, 0, 0))


def _half_hull_piece(t0: float, t1: float, n_stations: int) -> cq.Shape:
    """A solid loft between t0 and t1, sliced to keep only the lower half (z <= 0) of each
    superellipse station — a rounded keel under a flat deck, without the loft ever having to
    represent that flat/curved seam directly (which is what made shell() unreliable)."""
    wires = []
    for i in range(n_stations):
        t = t0 + (t1 - t0) * i / (n_stations - 1)
        half_width, half_depth = _outer_profile(t)
        wires.append(_superellipse_wire(t * LENGTH, half_width, half_depth))
    loft = cq.Solid.makeLoft(wires, ruled=False)
    top_half = cq.Solid.makeBox(LENGTH + 10, 40, 40, pnt=Vector(-5, -20, 0))
    return loft.cut(top_half)


def _build_hull() -> cq.Shape:
    bow_cap = _half_hull_piece(0.0, CAV_T0, STATIONS_BOW)
    mid = _half_hull_piece(CAV_T0, CAV_T1, STATIONS_MID)
    stern_cap = _half_hull_piece(CAV_T1, 1.0, STATIONS_STERN)
    mid_shell = cq.Workplane(obj=mid).faces(">Z").shell(-WALL, kind="intersection").val()
    return bow_cap.fuse(mid_shell).fuse(stern_cap)


def _add_flat_keel(hull: cq.Shape) -> cq.Shape:
    z_cut = -OUTER_DEPTH + FLAT_KEEL_SHAVE
    cutter = cq.Solid.makeBox(LENGTH + 10, 40, z_cut + 40, pnt=Vector(-5, -20, -40))
    return hull.cut(cutter)


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
    # normal=+Z (cutting down into the deck), xDir=+Y so the reading order runs
    # port(-Y)->starboard(+Y): readable by someone inside the hull facing the bow (-X),
    # for whom right-hand = +Y.
    plane = cq.Plane(origin=(BOW_TEXT_X, 0, 0), normal=(0, 0, 1), xDir=(0, 1, 0))
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


def _side_text_cutter(text: str, x: float, z: float, side: str) -> cq.Shape:
    """Text cut into the outer hull surface at length x, height z, on the given side
    ("port" or "starboard"). The cut is a single flat-plane extrusion tangent to the
    surface at that point — not a true surface projection — so it only stays shallow
    and even because the superellipse profile is nearly flat through this z range;
    see the "how hard would surface-conforming lettering be" discussion this shape
    was chosen to make moot.
    """
    t = x / LENGTH
    _, half_depth = _outer_profile(t)
    alpha = math.asin(min(1.0, abs(z) / half_depth) ** (SHAPE_N / 2))
    phi = (math.pi + alpha) if side == "port" else -alpha
    (y, z_surface), (normal_y, normal_z) = _surface_point_and_normal(t, phi)
    origin = (
        x,
        y + normal_y * SIDE_TEXT_OVERSHOOT,
        z_surface + normal_z * SIDE_TEXT_OVERSHOOT,
    )
    reading_dir = (1, 0, 0) if side == "port" else (-1, 0, 0)
    plane = cq.Plane(origin=origin, normal=(0, normal_y, normal_z), xDir=reading_dir)
    return cq.Compound.makeText(
        text,
        SIDE_TEXT_SIZE,
        -(SIDE_TEXT_DEPTH + SIDE_TEXT_OVERSHOOT),
        font="Arial",
        kind="bold",
        halign="center",
        valign="center",
        position=plane,
    )


def build() -> cq.Workplane:
    """Build the canoe and return it as a single-solid cadquery.Workplane."""
    hull = _build_hull()
    hull = _add_flat_keel(hull)
    hull = _add_thwarts(hull)
    hull = hull.cut(_bow_text_cutter())
    hull = hull.cut(_side_text_cutter(SIDE_TEXT_PORT, SIDE_TEXT_X, SIDE_TEXT_Z, "port"))
    hull = hull.cut(_side_text_cutter(SIDE_TEXT_STARBOARD, SIDE_TEXT_X, SIDE_TEXT_Z, "starboard"))
    hull = hull.rotate((0, 0, 0), (1, 0, 0), 180)  # print rim-down; see module docstring
    return cq.Workplane(obj=hull)
