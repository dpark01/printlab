"""Point-classification artifact: printlab.cad.probe.classify_points() -> probe_report.json.

Brings the "is this point inside the built solid" verification pattern (issue
#5.3) into the same structured-report discipline as the rest of PrintLab,
rather than leaving it to one-off scripts against OCP's solid classifier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from printlab.schemas.common import PrintLabArtifact

#: OCP's TopAbs_State, as returned by BRepClass3d_SolidClassifier.State().
Classification = Literal["IN", "OUT", "ON"]


class ProbedPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_mm: tuple[float, float, float]
    classification: Classification


class ProbeReport(PrintLabArtifact):
    """printlab.cad.probe.classify_points() -> probe_report.json.

    Classifies each requested point against the built solid (from `part.step`,
    the exact CAD boundary representation -- not the tessellated STL) using
    OCP's `BRepClass3d_SolidClassifier`, within `tolerance_mm` of the surface
    counting as "ON" rather than "IN"/"OUT".
    """

    model_config = ConfigDict(extra="forbid")

    input_path: Path
    input_sha256: str
    tolerance_mm: float
    points: list[ProbedPoint]
