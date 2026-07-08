"""Fast-lane tests for printlab_mcp.tools.

Imports only printlab_mcp.tools (never fastmcp), so it runs in CI's fast lane
with no MCP install. `stage_build` is monkeypatched so these never invoke the
CAD kernel -- the real CadQuery-backed end-to-end check lives in
tests/integration/test_mcp_smoke.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from printlab import pipeline
from printlab_mcp import tools

_MINIMAL_CONFIG = """\
[part]
name = "widget"
module = "part.py"

[profiles]
printer = "profiles/printer.yaml"
material = "profiles/material.yaml"
process = "profiles/process.yaml"
"""


def _write_config(example_dir: Path) -> None:
    (example_dir / "printlab.toml").write_text(_MINIMAL_CONFIG)


def _fake_build(calls: list):
    def build(config, output_dir):
        calls.append(output_dir)
        stl = output_dir / pipeline.ARTIFACT_FILENAMES["stl"]
        step = output_dir / pipeline.ARTIFACT_FILENAMES["step"]
        stl.write_text("solid x\nendsolid x\n")
        step.write_text("ISO-10303-21;\n")
        return step, stl

    return build


def test_ensure_built_builds_when_missing(tmp_path, monkeypatch):
    _write_config(tmp_path)
    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))

    config = tools.ensure_built(tmp_path, "check")

    assert len(calls) == 1
    assert config.name == "widget"
    assert (pipeline.default_output_dir(config, "check") / "part.stl").is_file()


def test_ensure_built_skips_when_present(tmp_path, monkeypatch):
    _write_config(tmp_path)
    output_dir = tmp_path / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")

    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))

    tools.ensure_built(tmp_path, "check")

    assert calls == []


@pytest.mark.parametrize("func", [tools.printlab_check, tools.printlab_orient, tools.printlab_render])
def test_bogus_example_dir_raises_pipeline_error(func, tmp_path):
    with pytest.raises(pipeline.PipelineError):
        func(str(tmp_path / "does_not_exist"))
