"""Point-in-solid classification against a built part's exact B-rep -- see
issue #5.3 (no structured way existed to check "is this point inside the
built solid" without a one-off OCP script).

Classifies against `part.step` (the exact CAD boundary representation OCCT
already produced), not the tessellated STL, so the answer is exact rather than
approximate-by-triangle-soup. Isolated in its own module -- like
printlab.fea.mesh -- because it needs OCP's lower-level API beyond what
cadquery's `Workplane` surface exposes.
"""

from __future__ import annotations

from pathlib import Path

import cadquery as cq
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT

from printlab.schemas.probe import Classification

#: Maps OCP's TopAbs_State to the classification string PrintLab reports.
_STATE_TO_CLASSIFICATION: dict[object, Classification] = {
    TopAbs_IN: "IN",
    TopAbs_OUT: "OUT",
    TopAbs_ON: "ON",
}


def load_solid(step_path: Path) -> cq.Shape:
    """Import `step_path` and return its single solid, mirroring
    printlab.cad.backend._single_shape's "exactly one solid" contract."""
    step_path = Path(step_path)
    result = cq.importers.importStep(str(step_path))
    shapes = result.vals()
    if len(shapes) != 1:
        raise ValueError(f"expected exactly one solid in {step_path}, got {len(shapes)}")
    return shapes[0]


def classify_points(
    shape: cq.Shape, points: list[tuple[float, float, float]], *, tolerance_mm: float
) -> list[Classification]:
    """Classify each point as "IN"/"OUT"/"ON" the solid, within `tolerance_mm`
    of the boundary counting as "ON" rather than "IN"/"OUT"."""
    classifier = BRepClass3d_SolidClassifier(shape.wrapped)
    results: list[Classification] = []
    for x, y, z in points:
        classifier.Perform(gp_Pnt(float(x), float(y), float(z)), tolerance_mm)
        results.append(_STATE_TO_CLASSIFICATION[classifier.State()])
    return results
