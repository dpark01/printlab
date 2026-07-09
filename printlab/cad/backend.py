"""CadQuery backend: load a parametric part, export STEP + STL with pinned tessellation.

STL tessellation is not free of the CAD kernel's version — the same geometry
tessellated by different OCCT versions can differ slightly. PrintLab pins the
linear/angular deflection *values* explicitly (rather than relying on a
library default that could change between versions) and records the OCCT
version used in run_manifest.json, so Tier-1 reproducibility only ever
requires matching pinned tool versions, never a hidden default.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq

#: Pinned explicitly rather than left at cadquery's default, so a future
#: cadquery/OCCT upgrade changing its default can't silently change our
#: tessellation without a deliberate profile bump.
DEFAULT_LINEAR_DEFLECTION_MM = 0.1
DEFAULT_ANGULAR_DEFLECTION_RAD = 0.1


@dataclass(frozen=True)
class ExportSettings:
    linear_deflection_mm: float = DEFAULT_LINEAR_DEFLECTION_MM
    angular_deflection_rad: float = DEFAULT_ANGULAR_DEFLECTION_RAD


class PartBuildError(RuntimeError):
    """Raised when a part module can't be loaded or its build() call fails."""


def load_build_function(part_py: Path, function_name: str = "build") -> Callable[[], cq.Workplane]:
    """Dynamically import an example's part.py and return its build() callable.

    Each example directory owns a `part.py` defining `build() -> cq.Workplane`.
    This is the *only* CAD source an agent should ever edit (SETUP.md's
    AGENTS.md rule: "edit only CAD source, never edit generated artifacts").
    """
    part_py = Path(part_py)
    if not part_py.is_file():
        raise PartBuildError(f"part module not found: {part_py}")

    spec = importlib.util.spec_from_file_location(f"printlab_part_{part_py.stem}", part_py)
    if spec is None or spec.loader is None:
        raise PartBuildError(f"could not load part module: {part_py}")
    module = importlib.util.module_from_spec(spec)
    # exec_module() writes a __pycache__/*.pyc next to part_py by default --
    # pure build byproduct, never useful to a caller, and it can land in an
    # example_dir PrintLab doesn't otherwise manage (e.g. a shared design
    # folder outside this repo). Suppress it for the duration of this import
    # only; restore afterward so it doesn't affect unrelated imports.
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode

    build_fn = getattr(module, function_name, None)
    if build_fn is None or not callable(build_fn):
        raise PartBuildError(f"{part_py} does not define a callable `{function_name}()`")
    return build_fn


def build_part(part_py: Path, function_name: str = "build") -> cq.Workplane:
    build_fn = load_build_function(part_py, function_name)
    try:
        result = build_fn()
    except Exception as exc:  # noqa: BLE001 - re-raised with part context
        raise PartBuildError(f"build() in {part_py} raised: {exc}") from exc
    if not isinstance(result, cq.Workplane):
        raise PartBuildError(f"build() in {part_py} must return a cadquery.Workplane, got {type(result)!r}")
    return result


def _single_shape(result: cq.Workplane) -> cq.Shape:
    shapes = result.vals()
    if len(shapes) != 1:
        raise PartBuildError(f"expected exactly one solid from build(), got {len(shapes)}")
    return shapes[0]


def export_step(result: cq.Workplane, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(_single_shape(result), str(path), exportType=cq.exporters.ExportTypes.STEP)
    return path


def export_stl(
    result: cq.Workplane,
    path: Path,
    settings: ExportSettings | None = None,
) -> Path:
    settings = settings or ExportSettings()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(
        _single_shape(result),
        str(path),
        exportType=cq.exporters.ExportTypes.STL,
        tolerance=settings.linear_deflection_mm,
        angularTolerance=settings.angular_deflection_rad,
        unit="MM",
    )
    return path
