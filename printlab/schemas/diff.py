"""Metrics-diff artifact: printlab_diff compares two printability_report.json
runs -- see issue #5.6. AGENTS.md already prescribes "compare metrics
numerically across runs, not visually"; this makes that mechanical instead of
requiring an agent to diff two JSON blobs by eye.

Only entries that actually changed are included -- an unchanged metric/check
is not signal, and AGENTS.md's own guidance is to reason about what moved.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from printlab.schemas.common import PrintLabArtifact, Status


class MetricDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    value_a: float | int | bool | str | None
    value_b: float | int | bool | str | None
    #: `value_b - value_a` when both values are numeric (int/float, excluding
    #: bool); `None` when either side is missing, non-numeric, or a bool.
    delta: float | None = None


class CheckStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status_a: Status | None
    status_b: Status | None


class MetricsDiffReport(PrintLabArtifact):
    """printlab_diff(report_a, report_b) -> what changed between two
    printability_report.json runs.

    `metric_deltas` covers `metrics{}` keys present in either report whose
    value differs; `check_changes` covers `checks[]` entries (matched by
    `name`) whose `status` differs, including a check appearing in only one
    report (the missing side is `None`).
    """

    model_config = ConfigDict(extra="forbid")

    report_a: str
    report_b: str
    metric_deltas: list[MetricDelta] = Field(default_factory=list)
    check_changes: list[CheckStatusChange] = Field(default_factory=list)
