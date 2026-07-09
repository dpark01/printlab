"""Offscreen renderer tests: pure trimesh + matplotlib/Agg, no CAD kernel and
no slicer -- same fast-lane rationale as tests/unit/test_mesh_overhangs.py.

A synthetic box is enough to exercise every framing/camera path; correctness of
the *pixels* isn't asserted (matplotlib-version-dependent), only that a real,
non-blank PNG of the requested size was produced and that the JSON metadata is
hash-stable.
"""

from __future__ import annotations

import numpy
import pytest
import trimesh
from PIL import Image

from printlab.determinism import hash_artifact, hash_file
from printlab.rendering import (
    PRESET_VIEWS,
    CameraView,
    render_png_filename,
    render_views,
)
from printlab.schemas import Status
from printlab.schemas.rendering import RenderReport

_WIDTH_PX = 640
_HEIGHT_PX = 480

# A shaded box against the background produces real per-pixel variance; every
# preset measured here empirically at std ~16-25 (lowest: "top" at ~16.5), so
# 5.0 is a ~3x-margin floor that a blank/failed render (flat color, std ~0)
# cannot clear.
_MIN_PIXEL_STD = 5.0


def _box() -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(10.0, 20.0, 30.0))


def test_presets_produce_real_png_files(tmp_path):
    requested = [PRESET_VIEWS[name] for name in ("iso", "front", "top")]
    views = render_views(
        _box(), tmp_path, views=requested, width_px=_WIDTH_PX, height_px=_HEIGHT_PX
    )

    assert len(views) == len(requested)
    for view in views:
        path = view.output_path
        assert path.exists()
        assert path.name == render_png_filename(view.label)

        img = Image.open(path)
        assert img.format == "PNG"
        assert img.size == (_WIDTH_PX, _HEIGHT_PX)

        arr = numpy.asarray(img.convert("RGB"))
        assert arr.std() > _MIN_PIXEL_STD


def test_render_report_is_ok_and_fingerprints_input(tmp_path):
    mesh = _box()
    requested = [PRESET_VIEWS[name] for name in ("iso", "front", "top")]
    views = render_views(mesh, tmp_path, views=requested)

    # render_views operates on an in-memory mesh, so the STL fingerprint is a
    # caller responsibility -- mirror what the pipeline integration will do.
    stl_path = tmp_path / "part.stl"
    mesh.export(stl_path)
    report = RenderReport(
        input_path=stl_path, input_sha256=hash_file(stl_path), views=views
    )

    assert report.status is Status.OK
    assert len(report.views) == len(requested)
    assert isinstance(report.input_sha256, str) and report.input_sha256


def test_render_report_hash_is_stable(tmp_path):
    mesh = _box()
    requested = [PRESET_VIEWS[name] for name in ("iso", "front", "top")]
    stl_path = tmp_path / "part.stl"
    mesh.export(stl_path)
    input_sha256 = hash_file(stl_path)

    # Two independent renders into the SAME dir: identical inputs (mesh, views,
    # output paths) must yield an identical artifact hash. Deliberately NOT
    # asserting the PNG bytes match -- those are matplotlib-version-dependent
    # (see printlab.schemas.rendering); don't "strengthen" this into a flaky
    # pixel comparison.
    views_a = render_views(mesh, tmp_path, views=requested)
    views_b = render_views(mesh, tmp_path, views=requested)
    report_a = RenderReport(input_path=stl_path, input_sha256=input_sha256, views=views_a)
    report_b = RenderReport(input_path=stl_path, input_sha256=input_sha256, views=views_b)

    assert hash_artifact(report_a) == hash_artifact(report_b)


def test_custom_camera_view_angles_are_echoed(tmp_path):
    custom = CameraView("custom", elevation_deg=12.5, azimuth_deg=47.0)
    views = render_views(_box(), tmp_path, views=[custom])

    assert len(views) == 1
    rendered = views[0]
    assert rendered.label == "custom"
    assert rendered.elevation_deg == 12.5
    assert rendered.azimuth_deg == 47.0
    assert rendered.roll_deg == 0.0


def test_grid_layout_composites_into_one_double_size_png(tmp_path):
    requested = [PRESET_VIEWS[name] for name in ("top", "front", "right", "iso")]
    views = render_views(
        _box(), tmp_path, views=requested, width_px=_WIDTH_PX, height_px=_HEIGHT_PX, layout="grid"
    )

    assert len(views) == len(requested)
    output_paths = {view.output_path for view in views}
    assert len(output_paths) == 1  # every view shares the one composite file
    (output_path,) = output_paths
    assert output_path.exists()

    img = Image.open(output_path)
    assert img.format == "PNG"
    # Grid canvas is double the per-panel size, so tiling doesn't shrink detail.
    assert img.size == (_WIDTH_PX * 2, _HEIGHT_PX * 2)
    for view in views:
        assert view.width_px == _WIDTH_PX * 2
        assert view.height_px == _HEIGHT_PX * 2


def test_grid_layout_rejects_more_than_four_views(tmp_path):
    requested = [PRESET_VIEWS[name] for name in ("top", "front", "right", "iso", "back")]
    with pytest.raises(ValueError):
        render_views(_box(), tmp_path, views=requested, layout="grid")


def test_focus_center_and_radius_zoom_without_error(tmp_path):
    # Pixel correctness isn't asserted (matplotlib-version-dependent, per
    # module docstring) -- only that a focused render still produces a real,
    # correctly-sized, non-blank PNG instead of erroring or collapsing.
    requested = [PRESET_VIEWS["iso"]]
    views = render_views(
        _box(),
        tmp_path,
        views=requested,
        width_px=_WIDTH_PX,
        height_px=_HEIGHT_PX,
        focus_center=(0.0, 0.0, 15.0),
        focus_radius=2.0,
    )

    assert len(views) == 1
    img = Image.open(views[0].output_path)
    assert img.size == (_WIDTH_PX, _HEIGHT_PX)
    arr = numpy.asarray(img.convert("RGB"))
    assert arr.std() > _MIN_PIXEL_STD


def test_focus_is_clamped_to_mesh_bounds(tmp_path):
    # A focus_radius far larger than the mesh, centered outside it entirely,
    # must not crash -- _fit_axes clamps to mesh.bounds rather than framing
    # empty space.
    requested = [PRESET_VIEWS["iso"]]
    views = render_views(
        _box(),
        tmp_path,
        views=requested,
        focus_center=(1000.0, 1000.0, 1000.0),
        focus_radius=1.0,
    )
    assert Image.open(views[0].output_path).format == "PNG"
