"""Printability evaluation artifact: printlab.evaluation -> printability_report.json.

Deliberately has no composite 0-100 score in v0.1: an uncalibrated hand-weighted
scalar is noise, and an agent optimizing it would chase artifacts of the
weighting rather than real design improvements. Instead this exposes raw
metrics plus independent pass/warning/fail checks; scoring is deferred until
there's calibration data to justify weights (see SETUP.md deviations).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import PrintLabArtifact, Status


class PrintabilityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Status
    message: str
    metric_value: float | int | bool | str | None = None
    threshold: float | int | None = None


class PrintabilityReport(PrintLabArtifact):
    model_config = ConfigDict(extra="forbid")

    metrics: dict[str, float | int | bool | str | None] = Field(default_factory=dict)
    checks: list[PrintabilityCheck] = Field(default_factory=list)

    @property
    def failure_count(self) -> int:
        return sum(1 for check in self.checks if check.status is Status.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for check in self.checks if check.status is Status.WARNING)
