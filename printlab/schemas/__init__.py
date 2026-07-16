"""Shared Pydantic artifact schemas, imported by every pipeline stage.

Every JSON artifact PrintLab writes (mesh_report.json, slice results,
gcode_report.json, printability_report.json, run_manifest.json) is defined
exactly once here, so the shape agents read is defined in one place instead of
duplicated per stage.
"""

from __future__ import annotations

from printlab.schemas.cad import CadBuildReport
from printlab.schemas.common import (
    SCHEMA_VERSION,
    ArtifactError,
    BBox,
    PrintLabArtifact,
    Status,
)
from printlab.schemas.diff import CheckStatusChange, MetricDelta, MetricsDiffReport
from printlab.schemas.evaluation import PrintabilityCheck, PrintabilityReport
from printlab.schemas.export import ExportedFile, ExportReport
from printlab.schemas.fea import FEALoadCase, FEAMeshPreviewReport, FEAReport
from printlab.schemas.gcode import GCodeReport
from printlab.schemas.mesh import MeshRepairReport, MeshReport
from printlab.schemas.orientation import OrientationCandidate, OrientationSearchReport
from printlab.schemas.probe import ProbedPoint, ProbeReport
from printlab.schemas.profiles import MaterialProfile, PrinterProfile, ProcessProfile
from printlab.schemas.provenance import RunManifest
from printlab.schemas.rendering import RenderedView, RenderReport
from printlab.schemas.slicing import Capabilities, SliceRequest, SliceResult

__all__ = [
    "SCHEMA_VERSION",
    "ArtifactError",
    "BBox",
    "CadBuildReport",
    "Capabilities",
    "CheckStatusChange",
    "ExportReport",
    "ExportedFile",
    "FEALoadCase",
    "FEAMeshPreviewReport",
    "FEAReport",
    "GCodeReport",
    "MaterialProfile",
    "MeshRepairReport",
    "MeshReport",
    "MetricDelta",
    "MetricsDiffReport",
    "OrientationCandidate",
    "OrientationSearchReport",
    "PrintLabArtifact",
    "PrintabilityCheck",
    "PrintabilityReport",
    "PrinterProfile",
    "ProbeReport",
    "ProbedPoint",
    "ProcessProfile",
    "RenderReport",
    "RenderedView",
    "RunManifest",
    "SliceRequest",
    "SliceResult",
    "Status",
]

#: All artifact model classes that get a committed JSON Schema under
#: docs/schemas/. Keep in sync with __all__ above; tests assert this.
ARTIFACT_MODELS = [
    CadBuildReport,
    MeshReport,
    MeshRepairReport,
    OrientationSearchReport,
    RenderReport,
    FEAReport,
    FEAMeshPreviewReport,
    ProbeReport,
    ExportReport,
    MetricsDiffReport,
    SliceRequest,
    SliceResult,
    GCodeReport,
    PrintabilityReport,
    RunManifest,
    PrinterProfile,
    MaterialProfile,
    ProcessProfile,
]
