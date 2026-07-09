"""Offscreen render artifact: printlab.rendering.render_views() -> RenderReport.

The image counterpart to printlab.reporting (markdown/html). A render is a set
of matplotlib/Agg PNGs of a mesh from preset camera angles, plus this JSON
describing how each was framed.

The PNG *bytes* are deliberately NOT hashed or asserted identical across runs:
matplotlib's rasterizer produces version-dependent pixels (antialiasing,
font/library minutiae), the same reason part.stl's bytes are excluded from the
run manifest's reproducibility hash (see printlab.determinism -- OCCT
tessellation is version-dependent). Only this JSON's camera/metadata fields
(labels, angles, dimensions) are the deterministic, hash-stable record of a
render; that is what hash_artifact() covers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import PrintLabArtifact


class RenderedView(BaseModel):
    """One rendered PNG and the camera that produced it.

    Echoes the CameraView angles back (see printlab.rendering.mpl) so the JSON
    fully documents how the image was framed without needing to reconstruct the
    view from the filename.
    """

    model_config = ConfigDict(extra="forbid")

    label: str
    elevation_deg: float
    azimuth_deg: float
    roll_deg: float = 0.0
    output_path: Path
    width_px: int
    height_px: int


class RenderReport(PrintLabArtifact):
    """printlab.rendering.render_views() -> render_report.json.

    `input_sha256`/`input_path` fingerprint the source STL; they are supplied
    by the caller (the pipeline integration), since render_views() operates on
    an in-memory trimesh.Trimesh rather than a file path -- see
    printlab.rendering.mpl.
    """

    model_config = ConfigDict(extra="forbid")

    input_path: Path
    input_sha256: str
    views: list[RenderedView] = Field(default_factory=list)
    layout: Literal["separate", "grid"] = Field(
        default="separate",
        description=(
            "'separate' writes one PNG per view (each view's own output_path). "
            "'grid' composites all views (up to 4) into a single 2x2 PNG -- "
            "every RenderedView in `views` then shares that one output_path."
        ),
    )
    focus_center: tuple[float, float, float] | None = Field(
        default=None,
        description=(
            "Region-of-interest override, in the part's native coordinate "
            "frame: when set (with focus_radius), every view is framed on a "
            "fixed cube around this point instead of the full mesh bounds."
        ),
    )
    focus_radius: float | None = Field(
        default=None,
        description="Half-width (mm) of the focus_center cube; None means no zoom override was applied.",
    )
