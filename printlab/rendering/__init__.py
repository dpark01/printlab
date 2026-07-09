"""Offscreen mesh rendering: the image counterpart to printlab.reporting.

See printlab.rendering.mpl for the renderer and printlab.schemas.rendering for
the artifact it produces.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import trimesh

from printlab.determinism import hash_file


def render_png_filename(label: str) -> str:
    """Single source of truth for a rendered view's filename.

    PNGs get one file per camera angle, so unlike the static per-stage filenames
    elsewhere they can't live in a fixed dict -- this derives them by label.
    """
    return f"render_{label}.png"


from printlab.rendering.mpl import (  # noqa: E402 -- render_png_filename must be defined first (mpl imports it)
    DEFAULT_VIEWS,
    PRESET_VIEWS,
    CameraView,
    render_mesh_png,
    render_views,
)
from printlab.schemas import RenderReport  # noqa: E402


def render(
    stl_path: Path,
    output_dir: Path,
    *,
    views: Sequence[str | CameraView] = DEFAULT_VIEWS,
    width_px: int = 800,
    height_px: int = 600,
    layout: Literal["separate", "grid"] = "separate",
    focus_center: tuple[float, float, float] | None = None,
    focus_radius: float | None = None,
) -> RenderReport:
    """Load an STL and render it from each requested view.

    Not part of `printlab all`'s critical path (like printlab.mesh.orient):
    explicitly invoked via `printlab render`. String entries in `views` are
    resolved against PRESET_VIEWS; pass a `CameraView` directly for a custom
    angle not covered by a preset. `layout="grid"` composites up to 4 views
    into one PNG instead of one file per view (see `render_views`).
    `focus_center`/`focus_radius` zoom into a fixed region instead of framing
    the whole mesh -- useful for a small feature on an otherwise large part.
    """
    stl_path = Path(stl_path)
    input_sha256 = hash_file(stl_path)
    mesh = trimesh.load(stl_path, force="mesh")

    resolved_views = [PRESET_VIEWS[v] if isinstance(v, str) else v for v in views]
    rendered = render_views(
        mesh,
        output_dir,
        views=resolved_views,
        width_px=width_px,
        height_px=height_px,
        layout=layout,
        focus_center=focus_center,
        focus_radius=focus_radius,
    )

    return RenderReport(
        input_path=stl_path,
        input_sha256=input_sha256,
        views=rendered,
        layout=layout,
        focus_center=focus_center,
        focus_radius=focus_radius,
    )


__all__ = [
    "DEFAULT_VIEWS",
    "PRESET_VIEWS",
    "CameraView",
    "render",
    "render_mesh_png",
    "render_png_filename",
    "render_views",
]
