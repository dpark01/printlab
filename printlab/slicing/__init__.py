"""Slicing stage: a slicer-independent backend registry.

`get_backend()` / `available_backends()` are how the pipeline and CLI look up
a backend by name without importing a specific module, and how tests key
capability-gated skip logic off "is this backend's binary present" rather
than hard-coding backend names.
"""

from __future__ import annotations

from printlab.schemas import Capabilities
from printlab.slicing.bambu import BambuStudioBackend
from printlab.slicing.base import PrusaLikeBackend, SlicerBackend
from printlab.slicing.prusaslicer import PrusaSlicerBackend

_BACKENDS: dict[str, type[SlicerBackend]] = {
    "prusaslicer": PrusaSlicerBackend,
    "bambu": BambuStudioBackend,
}


def available_backend_names() -> list[str]:
    return sorted(_BACKENDS)


def get_backend(name: str) -> SlicerBackend:
    try:
        return _BACKENDS[name]()
    except KeyError as exc:
        raise ValueError(f"unknown slicer backend {name!r}; available: {available_backend_names()}") from exc


def detect_all() -> dict[str, Capabilities]:
    return {name: get_backend(name).detect() for name in available_backend_names()}


__all__ = [
    "BambuStudioBackend",
    "PrusaLikeBackend",
    "PrusaSlicerBackend",
    "SlicerBackend",
    "available_backend_names",
    "detect_all",
    "get_backend",
]
