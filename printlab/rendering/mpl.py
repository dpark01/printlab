"""Offscreen mesh renderer: matplotlib/Agg PNGs from preset camera angles.

Builds a Figure + FigureCanvasAgg directly and never touches matplotlib.pyplot
-- pyplot carries global figure-manager state and picks an interactive backend,
neither of which is safe under a deterministic, potentially threaded pipeline.
The Agg canvas is pure offscreen rasterization with no such contention.

Framing is derived entirely from mesh.bounds (fitted limits + a box aspect that
matches the real extents), so a view is fully specified by two angles and needs
no free "camera distance" knob -- keeping renders deterministic per mesh. An
optional `focus_center`/`focus_radius` override (see `_fit_axes`) substitutes a
fixed cube for the full mesh bounds, for zooming into a small feature on an
otherwise large part; it is still derived from the mesh (clamped to its bounds),
not an arbitrary free camera distance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import trimesh
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from printlab.rendering import render_png_filename
from printlab.schemas import RenderedView

#: layout="grid" tiles at most this many views into one 2x2 composite --
#: see render_mesh_grid_png.
MAX_GRID_VIEWS = 4

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


def _fit_axes(
    ax,
    mesh: trimesh.Trimesh,
    *,
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
) -> None:
    mins, maxs = mesh.bounds
    if focus_center is not None and focus_radius is not None:
        # Axis-aligned cube of side 2*focus_radius centered on focus_center,
        # clamped to the mesh's own bounds -- a region-of-interest override
        # for small features that would otherwise render as a few illegible
        # pixels under the default full-mesh framing (see module docstring).
        mins = [max(float(mins[i]), focus_center[i] - focus_radius) for i in range(3)]
        maxs = [min(float(maxs[i]), focus_center[i] + focus_radius) for i in range(3)]
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


def _add_mesh_to_axes(
    ax,
    mesh: trimesh.Trimesh,
    view: CameraView,
    *,
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
) -> None:
    collection = Poly3DCollection(
        mesh.triangles,
        facecolor=_FACE_COLOR,
        edgecolor=_EDGE_COLOR,
        linewidths=_EDGE_LINEWIDTH,
    )
    ax.add_collection3d(collection)
    _fit_axes(ax, mesh, focus_center=focus_center, focus_radius=focus_radius)
    ax.view_init(elev=view.elevation_deg, azim=view.azimuth_deg, roll=view.roll_deg)
    ax.set_axis_off()


def render_mesh_png(
    mesh: trimesh.Trimesh,
    output_path: Path,
    *,
    view: CameraView,
    width_px: int = 800,
    height_px: int = 600,
    dpi: int = 100,
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
) -> Path:
    output_path = Path(output_path)
    figure = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    canvas = FigureCanvasAgg(figure)
    ax = figure.add_subplot(projection="3d")

    _add_mesh_to_axes(ax, mesh, view, focus_center=focus_center, focus_radius=focus_radius)

    canvas.print_png(str(output_path))
    return output_path


def render_mesh_grid_png(
    mesh: trimesh.Trimesh,
    output_path: Path,
    *,
    views: Sequence[CameraView],
    width_px: int = 1600,
    height_px: int = 1200,
    dpi: int = 100,
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
) -> Path:
    """Composite up to MAX_GRID_VIEWS views into one 2x2 grid Figure -- the
    single-view equivalent is render_mesh_png. `width_px`/`height_px` here are
    the *whole composite canvas*, not one panel: callers should double their
    usual per-panel size (see printlab.rendering.render_views), so tiling
    doesn't shrink each panel below what a separate render would produce."""
    if len(views) > MAX_GRID_VIEWS:
        raise ValueError(f"layout='grid' supports at most {MAX_GRID_VIEWS} views, got {len(views)}")
    output_path = Path(output_path)
    figure = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    canvas = FigureCanvasAgg(figure)

    for i, view in enumerate(views):
        ax = figure.add_subplot(2, 2, i + 1, projection="3d")
        _add_mesh_to_axes(ax, mesh, view, focus_center=focus_center, focus_radius=focus_radius)
        ax.set_title(view.label, fontsize=8)

    canvas.print_png(str(output_path))
    return output_path


def render_views(
    mesh: trimesh.Trimesh,
    output_dir: Path,
    *,
    views: Sequence[CameraView],
    width_px: int = 800,
    height_px: int = 600,
    layout: Literal["separate", "grid"] = "separate",
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
) -> list[RenderedView]:
    """Render `mesh` into `output_dir`, returning a RenderedView record per
    requested view. Does not fingerprint the source STL: the caller holds the
    input path/hash and assembles the RenderReport (see
    printlab.schemas.rendering).

    `layout="separate"` (default) writes one PNG per view, each sized
    `width_px`x`height_px`. `layout="grid"` composites all views (at most
    MAX_GRID_VIEWS) into one PNG at `2*width_px`x`2*height_px`, so the
    per-panel pixel budget matches what `"separate"` would have produced
    instead of shrinking to fit -- every RenderedView returned then shares
    that one composite `output_path`."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if layout == "grid":
        grid_width_px = width_px * 2
        grid_height_px = height_px * 2
        output_path = output_dir / render_png_filename("grid")
        render_mesh_grid_png(
            mesh,
            output_path,
            views=views,
            width_px=grid_width_px,
            height_px=grid_height_px,
            focus_center=focus_center,
            focus_radius=focus_radius,
        )
        return [
            RenderedView(
                label=view.label,
                elevation_deg=view.elevation_deg,
                azimuth_deg=view.azimuth_deg,
                roll_deg=view.roll_deg,
                output_path=output_path,
                width_px=grid_width_px,
                height_px=grid_height_px,
            )
            for view in views
        ]

    rendered: list[RenderedView] = []
    for view in views:
        output_path = output_dir / render_png_filename(view.label)
        render_mesh_png(
            mesh,
            output_path,
            view=view,
            width_px=width_px,
            height_px=height_px,
            focus_center=focus_center,
            focus_radius=focus_radius,
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
