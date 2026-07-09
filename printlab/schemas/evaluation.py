"""Printability evaluation artifact: printlab.evaluation -> printability_report.json.

The primary output is still raw `metrics` plus independent pass/warning/fail
`checks` — those are what an agent should reason about. There is now also a
`provisional_score` (0-100), but it is explicitly UNCALIBRATED and must not be
optimized:

- `provisional_score` is a crude triage number derived from a fixed, arbitrary
  per-check penalty (see `printlab.evaluation.printability`), not from any
  weighting justified by data. It exists so a human skimming many parts can
  sort them roughly; it is not ground truth about printability.
- `score_calibrated` is always `False` in v1. It is the machine-readable "do
  not trust this as ground truth" signal: a caller branches on it directly,
  without having to read this docstring. It flips to `True` only once weights
  are derived from real print outcomes (which do not exist yet).

Calibration is still pending precisely because an uncalibrated hand-weighted
scalar is noise an agent would learn to game rather than a real signal. Until
`score_calibrated` is `True`, hill-climbing `provisional_score` is off-limits:
reason about the individual `checks[]` and `metrics{}` instead (see SETUP.md
deviations and AGENTS.md).
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

    provisional_score: int = Field(
        default=100,
        description=(
            "UNCALIBRATED 0-100 triage number from a fixed, arbitrary "
            "per-check penalty (see printlab.evaluation.printability). "
            "Integer, not float: a discrete penalty scheme produces round "
            "numbers, and a float would imply precision this does not have. "
            "Do not optimize it -- reason about `checks`/`metrics` instead. "
            "Only meaningful once `score_calibrated` is True."
        ),
    )
    score_calibrated: bool = Field(
        default=False,
        description=(
            "Always False in v1: the score's weights are not derived from "
            "real print outcomes. This is the machine-readable \"do not "
            "trust `provisional_score` as ground truth\" flag -- branch on "
            "it instead of reading a docstring."
        ),
    )

    @property
    def failure_count(self) -> int:
        return sum(1 for check in self.checks if check.status is Status.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for check in self.checks if check.status is Status.WARNING)
