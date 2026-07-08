"""A thin-walled tube: a calibration part for wall-thickness analysis.

Deliberately different from the bracket/hook/canoe: this part exists to
exercise `printlab.mesh.wall_thickness` (and the `min_wall_thickness`
printability check) with a wall that is genuinely, robustly below the
printer's `min_feature_size_mm` (0.4mm on the Bambu A1) -- not as a
sliver-edge artifact, but as a large, uniform region a percentile-based SDF
estimate reliably reads as thin.

A coaxial tube (outer cylinder minus a slightly smaller inner cylinder) is
used rather than a flat panel for exactly that reason: a flat box tessellates
into a handful of triangles per face, too few for the 5th-percentile estimate
to be meaningful, whereas the tube's curved walls tessellate into dozens of
facets around the circumference, so a large fraction of all faces cast a ray
straight across the 0.25mm wall to the opposite surface and read ~0.25mm.
Outer and inner cylinders are coaxial and share the same angular tessellation,
so the wall stays a uniform 0.25mm everywhere (chord error ~0.02mm at this
radius, well under the wall thickness) and the mesh stays manifold/watertight
-- a legitimately thin-walled but valid part, not a broken shell.
"""

from __future__ import annotations

import cadquery as cq
from cadquery import Vector

# All dimensions in millimeters.
OUTER_DIAMETER = 30.0  # outer diameter of the tube
WALL = 0.25  # radial wall thickness -- deliberately well below the A1's 0.4mm min feature size
HEIGHT = 24.0  # tube height; tall enough that the annular end faces read clearly thick, not thin


def build() -> cq.Workplane:
    """Build the thin-walled tube and return it as a single-solid cadquery.Workplane."""
    outer_radius = OUTER_DIAMETER / 2
    inner_radius = outer_radius - WALL

    outer = cq.Solid.makeCylinder(outer_radius, HEIGHT, pnt=Vector(0, 0, 0))
    inner = cq.Solid.makeCylinder(inner_radius, HEIGHT, pnt=Vector(0, 0, 0))
    solid = outer.cut(inner)

    return cq.Workplane(obj=solid)
