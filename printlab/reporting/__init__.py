"""Reporting stage: secondary human-facing renderings of pipeline artifacts."""

from __future__ import annotations

from printlab.reporting.html import render as render_html
from printlab.reporting.markdown import render as render_markdown

__all__ = ["render_html", "render_markdown"]
