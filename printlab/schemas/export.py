"""Export-bundle artifact: printlab_export copies named deliverables out of the
disposable `output/<backend>/` tree into a durable destination -- see issue
#5.5. Mirrors the rest of PrintLab's philosophy: a deterministic, structured
record of what was copied (and what was requested but unavailable) rather than
ad hoc `cp` commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import PrintLabArtifact

#: "render" bundles every render_*.png present in the source output dir into
#: one dest_dir; the rest are 1:1 files.
ExportFormat = Literal["stl", "step", "3mf", "gcode", "render"]


class ExportedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: ExportFormat
    source: Path
    dest: Path


class ExportReport(PrintLabArtifact):
    """printlab_export(...) -> what was actually copied.

    A requested format whose source artifact doesn't exist yet (e.g. `gcode`
    without a prior `printlab_all`, `render` without a prior `printlab_render`)
    is recorded as a `warning`-status `errors[]` entry, not a hard failure --
    the other requested formats still get copied.
    """

    model_config = ConfigDict(extra="forbid")

    example_dir: Path
    backend: str
    dest_dir: Path
    name_prefix: str
    exported: list[ExportedFile] = Field(default_factory=list)
