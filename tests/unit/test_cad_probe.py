"""Real-CadQuery/OCP test for printlab.cad.probe -- issue #5.3's
point-in-solid classification. cadquery/OCP are hard dependencies (not the
`fea` extra), so this runs unconditionally, unlike the gmsh/ccx-gated tests.
"""

from __future__ import annotations

import cadquery as cq

from printlab.cad import export_step
from printlab.cad.probe import classify_points, load_solid


def _unit_box_step(tmp_path):
    """A 10x10x10 mm box centered at the origin, exported to STEP."""
    box = cq.Workplane("XY").box(10, 10, 10)
    return export_step(box, tmp_path / "part.step")


def test_classify_points_center_is_in(tmp_path):
    step_path = _unit_box_step(tmp_path)
    shape = load_solid(step_path)

    (classification,) = classify_points(shape, [(0.0, 0.0, 0.0)], tolerance_mm=1e-6)

    assert classification == "IN"


def test_classify_points_far_outside_is_out(tmp_path):
    step_path = _unit_box_step(tmp_path)
    shape = load_solid(step_path)

    (classification,) = classify_points(shape, [(100.0, 0.0, 0.0)], tolerance_mm=1e-6)

    assert classification == "OUT"


def test_classify_points_on_face_is_on(tmp_path):
    step_path = _unit_box_step(tmp_path)
    shape = load_solid(step_path)

    # The box spans [-5, 5] on every axis; (5, 0, 0) sits exactly on the +X face.
    (classification,) = classify_points(shape, [(5.0, 0.0, 0.0)], tolerance_mm=1e-6)

    assert classification == "ON"


def test_classify_points_handles_a_mixed_batch_in_one_call(tmp_path):
    step_path = _unit_box_step(tmp_path)
    shape = load_solid(step_path)

    classifications = classify_points(
        shape,
        [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (5.0, 0.0, 0.0)],
        tolerance_mm=1e-6,
    )

    assert classifications == ["IN", "OUT", "ON"]


