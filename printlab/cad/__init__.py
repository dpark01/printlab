"""CAD stage: build a parametric part and export STEP/STL with pinned tessellation."""

from __future__ import annotations

from printlab.cad.backend import (
    DEFAULT_ANGULAR_DEFLECTION_RAD,
    DEFAULT_LINEAR_DEFLECTION_MM,
    CadQueryBackend,
    ExportSettings,
    PartBuildError,
    build_part,
    export_step,
    export_stl,
    load_build_function,
)
from printlab.cad.base import CadBackend, CadBuildError, CadBuildRequest, CadBuildResult
from printlab.cad.openscad import OpenSCADBackend

_BACKENDS: dict[str, CadBackend] = {
    "cadquery": CadQueryBackend(),
    "openscad": OpenSCADBackend(),
}


def get_cad_backend(name: str) -> CadBackend:
    try:
        return _BACKENDS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_BACKENDS))
        raise CadBuildError(f"unknown CAD backend {name!r}; available: {available}") from exc


def available_cad_backend_names() -> tuple[str, ...]:
    return tuple(sorted(_BACKENDS))


__all__ = [
    "DEFAULT_ANGULAR_DEFLECTION_RAD",
    "DEFAULT_LINEAR_DEFLECTION_MM",
    "CadBackend",
    "CadBuildError",
    "CadBuildRequest",
    "CadBuildResult",
    "CadQueryBackend",
    "ExportSettings",
    "OpenSCADBackend",
    "PartBuildError",
    "available_cad_backend_names",
    "build_part",
    "export_step",
    "export_stl",
    "get_cad_backend",
    "load_build_function",
]
