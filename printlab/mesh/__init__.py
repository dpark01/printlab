"""Mesh stage: geometry analysis, (best-effort) repair, and orientation
search over an exported STL."""

from __future__ import annotations

from printlab.mesh.analyze import analyze
from printlab.mesh.orientation import orient
from printlab.mesh.repair import repair

__all__ = ["analyze", "orient", "repair"]
