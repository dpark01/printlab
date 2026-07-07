"""G-code stage: the authoritative source of slicing metrics for every backend."""

from __future__ import annotations

from printlab.gcode.metrics import analyze
from printlab.gcode.parser import ParsedGcode, parse_gcode

__all__ = ["ParsedGcode", "analyze", "parse_gcode"]
