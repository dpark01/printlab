"""Backend-neutral contracts for turning CAD source into STEP and STL."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class CadBuildError(RuntimeError):
    """Raised when a CAD backend cannot produce the required artifacts."""


@dataclass(frozen=True)
class CadBuildRequest:
    source_path: Path
    output_dir: Path
    build_target: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CadBuildResult:
    backend_name: str
    step_path: Path
    stl_path: Path
    dependencies: tuple[Path, ...] = ()
    tool_versions: dict[str, str] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)


class CadBackend(ABC):
    """A source-language adapter that emits PrintLab's STEP/STL contract."""

    name: str

    @abstractmethod
    def build(self, request: CadBuildRequest) -> CadBuildResult:
        """Build ``request.source_path`` into ``request.output_dir``."""
