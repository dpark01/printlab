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

from printlab.cad.base import CadBackend, CadBuildError, CadBuildRequest, CadBuildResult

#: Pinned explicitly rather than left at cadquery's default, so a future
#: cadquery/OCCT upgrade changing its default can't silently change our
#: tessellation without a deliberate profile bump.
DEFAULT_LINEAR_DEFLECTION_MM = 0.1
DEFAULT_ANGULAR_DEFLECTION_RAD = 0.1


@dataclass(frozen=True)
class ExportSettings:
    linear_deflection_mm: float = DEFAULT_LINEAR_DEFLECTION_MM
    angular_deflection_rad: float = DEFAULT_ANGULAR_DEFLECTION_RAD


class PartBuildError(CadBuildError):
    """Raised when a part module can't be loaded or its build() call fails."""


def load_build_function(part_py: Path, function_name: str = "build") -> Callable[[], cq.Workplane]:
    """Dynamically import an example's part.py and return its build() callable.

    A CadQuery example owns a `.py` source defining `build() -> cq.Workplane`.
    This is the durable CAD source an agent may edit; generated output remains
    off limits (see AGENTS.md).
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


class CadQueryBackend(CadBackend):
    """Build a Python CadQuery module through the generic CAD contract."""

    name = "cadquery"

    def build(self, request: CadBuildRequest) -> CadBuildResult:
        build_target = request.build_target or "build"
        result = build_part(request.source_path, build_target)
        step_path = export_step(result, request.output_dir / "part.step")
        stl_path = export_stl(result, request.output_dir / "part.stl")
        return CadBuildResult(
            backend_name=self.name,
            step_path=step_path,
            stl_path=stl_path,
            dependencies=(request.source_path,),
            settings={
                "build_target": build_target,
                "linear_deflection_mm": DEFAULT_LINEAR_DEFLECTION_MM,
                "angular_deflection_rad": DEFAULT_ANGULAR_DEFLECTION_RAD,
            },
        )
