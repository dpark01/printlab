"""A two-support bridge: a calibration part for overhang/bridge analysis.

Deliberately different from the hook (examples/hook/part.py): the hook is a
one-sided cantilever, whose unsupported underside is a curved surface spanning
a range of angles. This bridge is the other canonical hard case -- a flat
horizontal deck carried between two legs, so the entire underside of the deck
*between* the legs is a downward-facing face at 90 degrees from vertical (the
maximum overhang severity) with nothing beneath it. That is exactly the
geometry that motivates bridge-length analysis (`printlab.mesh.bridges`) and
per-material safe-span limits: a slicer must bridge the gap in mid-air, and a
long enough span sags without support.

The gap between the legs sets the unsupported span (a 40mm clear gap, ~45mm
projected once the deck's depth is folded in -- both clearly beyond the hook's
cantilever numbers, and distinct from it in kind). The legs themselves are plain vertical prisms -- their
sides are vertical (safe) and their bottoms rest on the bed (excluded from
overhang accounting) -- so essentially all of this part's overhang area comes
from the one deliberate feature: the deck's unsupported underside.
"""

from __future__ import annotations

import cadquery as cq
from cadquery import Vector

# All dimensions in millimeters.
DEPTH = 20.0  # Y extent, shared by the legs and the deck
LEG_WIDTH = 12.0  # X extent of each leg
LEG_HEIGHT = 25.0  # Z height of the legs, from the bed up to the underside of the deck
GAP = 40.0  # clear horizontal distance between the legs -- the unsupported bridge span
DECK_THICKNESS = 6.0  # Z thickness of the horizontal deck spanning the legs

TOTAL_LENGTH = 2 * LEG_WIDTH + GAP  # X extent of the deck, resting fully on both legs


def build() -> cq.Workplane:
    """Build the bridge and return it as a single-solid cadquery.Workplane."""
    left_leg = cq.Solid.makeBox(LEG_WIDTH, DEPTH, LEG_HEIGHT, pnt=Vector(0, 0, 0))
    right_leg = cq.Solid.makeBox(
        LEG_WIDTH, DEPTH, LEG_HEIGHT, pnt=Vector(LEG_WIDTH + GAP, 0, 0)
    )
    deck = cq.Solid.makeBox(
        TOTAL_LENGTH, DEPTH, DECK_THICKNESS, pnt=Vector(0, 0, LEG_HEIGHT)
    )

    solid = left_leg.fuse(right_leg).fuse(deck)

    return cq.Workplane(obj=solid)
