"""Offscreen mesh renderer: matplotlib/Agg PNGs from preset camera angles.

Builds a Figure + FigureCanvasAgg directly and never touches matplotlib.pyplot
-- pyplot carries global figure-manager state and picks an interactive backend,
neither of which is safe under a deterministic, potentially threaded pipeline.
The Agg canvas is pure offscreen rasterization with no such contention.

Framing is derived entirely from mesh.bounds (fitted limits + a box aspect that
matches the real extents), so a view is fully specified by two angles and needs
no free "camera distance" knob -- keeping renders deterministic per mesh.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import trimesh
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from printlab.rendering import render_png_filename
from printlab.schemas import RenderedView

_MARGIN_FRAC = 0.1
_FACE_COLOR = "#b0b8c0"
_EDGE_COLOR = "#404040"
_EDGE_LINEWIDTH = 0.2


@dataclass(frozen=True)
class CameraView:
    label: str
    elevation_deg: float
    azimuth_deg: float
    roll_deg: float = 0.0


#: Z is up, matching PrintLab's default build direction (0, 0, 1): "top" looks
#: down the build axis, so these presets read the way a printer operator expects.
PRESET_VIEWS: dict[str, CameraView] = {
    "iso": CameraView("iso", 30.0, -60.0),
    "front": CameraView("front", 0.0, -90.0),
    "back": CameraView("back", 0.0, 90.0),
    "left": CameraView("left", 0.0, 180.0),
    "right": CameraView("right", 0.0, 0.0),
    "top": CameraView("top", 90.0, -90.0),
    "bottom": CameraView("bottom", -90.0, -90.0),
}
DEFAULT_VIEWS: tuple[str, ...] = ("iso", "front", "top")


def _fit_axes(ax, mesh: trimesh.Trimesh) -> None:
    mins, maxs = mesh.bounds
    extents = [float(maxs[i] - mins[i]) for i in range(3)]
    for i, setter in enumerate((ax.set_xlim, ax.set_ylim, ax.set_zlim)):
        # A zero extent (a flat part on some axis) would collapse the limits
        # onto a single value, which matplotlib rejects -- fall back to a unit
        # span centered on the plane so the render still frames cleanly.
        span = extents[i] if extents[i] > 0.0 else 1.0
        margin = span * _MARGIN_FRAC
        center = float(mins[i] + maxs[i]) / 2.0
        setter(center - span / 2.0 - margin, center + span / 2.0 + margin)
    ax.set_box_aspect([e if e > 0.0 else 1.0 for e in extents])


def render_mesh_png(
    mesh: trimesh.Trimesh,
    output_path: Path,
    *,
    view: CameraView,
    width_px: int = 800,
    height_px: int = 600,
    dpi: int = 100,
) -> Path:
    output_path = Path(output_path)
    figure = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    canvas = FigureCanvasAgg(figure)
    ax = figure.add_subplot(projection="3d")

    collection = Poly3DCollection(
        mesh.triangles,
        facecolor=_FACE_COLOR,
        edgecolor=_EDGE_COLOR,
        linewidths=_EDGE_LINEWIDTH,
    )
    ax.add_collection3d(collection)

    _fit_axes(ax, mesh)
    ax.view_init(elev=view.elevation_deg, azim=view.azimuth_deg, roll=view.roll_deg)
    ax.set_axis_off()

    canvas.print_png(str(output_path))
    return output_path


def render_views(
    mesh: trimesh.Trimesh,
    output_dir: Path,
    *,
    views: Sequence[CameraView],
    width_px: int = 800,
    height_px: int = 600,
) -> list[RenderedView]:
    """Render `mesh` once per view into `output_dir`, returning a RenderedView
    record per image. Does not fingerprint the source STL: the caller holds the
    input path/hash and assembles the RenderReport (see
    printlab.schemas.rendering)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[RenderedView] = []
    for view in views:
        output_path = output_dir / render_png_filename(view.label)
        render_mesh_png(
            mesh,
            output_path,
            view=view,
            width_px=width_px,
            height_px=height_px,
        )
        rendered.append(
            RenderedView(
                label=view.label,
                elevation_deg=view.elevation_deg,
                azimuth_deg=view.azimuth_deg,
                roll_deg=view.roll_deg,
                output_path=output_path,
                width_px=width_px,
                height_px=height_px,
            )
        )
    return rendered
