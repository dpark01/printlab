"""Slicer backend abstraction.

`SlicerBackend` is the interface the pipeline talks to; it never speaks a
slicer's native dialect directly. `PrusaLikeBackend` exists because
PrusaSlicer, Bambu Studio, and (eventually) OrcaSlicer all descend from
Slic3r and share enough CLI/G-code conventions that binary discovery and
subprocess invocation are worth sharing -- only settings translation and
output-file discovery differ per backend.

Backends expose a `Capabilities` descriptor (see printlab.schemas.slicing) so
the pipeline can degrade gracefully and CI skip logic can key off "is this
backend's binary present" rather than hard-coding backend names.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from printlab.schemas import (
    Capabilities,
    MaterialProfile,
    PrinterProfile,
    ProcessProfile,
    SliceRequest,
    SliceResult,
)


class SlicerBackend(ABC):
    #: Short, stable identifier used in profile native_bundle keys, CLI
    #: --backend flags, and SliceResult.backend.
    name: str

    @abstractmethod
    def detect(self) -> Capabilities:
        """Report whether this backend's binary is present, and what it can do."""

    @abstractmethod
    def slice(
        self,
        request: SliceRequest,
        *,
        printer: PrinterProfile,
        material: MaterialProfile,
        process: ProcessProfile,
    ) -> SliceResult:
        """Slice `request.input_model`, writing outputs under `request.output_dir`."""


class PrusaLikeBackend(SlicerBackend):
    """Shared plumbing for Slic3r-lineage CLIs (PrusaSlicer, Bambu Studio, ...)."""

    #: Absolute paths to probe before falling back to a PATH lookup.
    candidate_paths: tuple[Path, ...] = ()
    binary_name: str = ""

    def find_binary(self) -> Path | None:
        for candidate in self.candidate_paths:
            if candidate.is_file():
                return candidate
        found = shutil.which(self.binary_name)
        return Path(found) if found else None

    def run_cli(
        self,
        binary: Path,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 600,
    ) -> subprocess.CompletedProcess[str]:
        # Never shell=True: args are passed as a list so profile/path values
        # can never be interpreted by a shell.
        return subprocess.run(
            [str(binary), *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
