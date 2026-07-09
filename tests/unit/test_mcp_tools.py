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

    config, output_dir = tools.ensure_built(tmp_path, "check")

    assert len(calls) == 1
    assert config.name == "widget"
    assert output_dir == pipeline.default_output_dir(config, "check")
    assert (output_dir / "part.stl").is_file()


def test_ensure_built_skips_when_present(tmp_path, monkeypatch):
    _write_config(tmp_path)
    output_dir = tmp_path / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")

    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))

    tools.ensure_built(tmp_path, "check")

    assert calls == []


def test_ensure_built_respects_output_dir_override(tmp_path, monkeypatch):
    _write_config(tmp_path)
    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))
    override_dir = tmp_path / "scratch"

    _config, resolved_output_dir = tools.ensure_built(tmp_path, "check", output_dir=override_dir)

    assert resolved_output_dir == override_dir
    assert calls == [override_dir]
    assert (override_dir / "part.stl").is_file()


@pytest.mark.parametrize("func", [tools.printlab_check, tools.printlab_orient, tools.printlab_render])
def test_bogus_example_dir_raises_pipeline_error(func, tmp_path):
    with pytest.raises(pipeline.PipelineError):
        func(str(tmp_path / "does_not_exist"))


def test_printlab_check_forwards_output_dir(tmp_path, monkeypatch):
    captured = {}

    def fake_run_check(example_dir, *, output_dir=None):
        captured["output_dir"] = output_dir
        return {"printability": "fake-report"}

    monkeypatch.setattr(pipeline, "run_check", fake_run_check)

    override_dir = tmp_path / "scratch"
    result = tools.printlab_check(str(tmp_path), output_dir=str(override_dir))

    assert result == "fake-report"
    assert captured["output_dir"] == override_dir


def test_printlab_all_forwards_output_dir_and_backend(tmp_path, monkeypatch):
    captured = {}

    def fake_run_all(example_dir, backend, *, output_dir=None):
        captured["backend"] = backend
        captured["output_dir"] = output_dir
        return {"printability": "fake-report"}

    monkeypatch.setattr(pipeline, "run_all", fake_run_all)

    override_dir = tmp_path / "scratch"
    result = tools.printlab_all(str(tmp_path), backend="prusaslicer", output_dir=str(override_dir))

    assert result == "fake-report"
    assert captured["backend"] == "prusaslicer"
    assert captured["output_dir"] == override_dir


def test_printlab_render_elevation_and_azimuth_build_custom_view(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))
    captured = {}

    def fake_stage_render(stl_path, output_dir, *, views, layout, focus_center, focus_radius):
        captured["views"] = views
        return "fake-report"

    monkeypatch.setattr(pipeline, "stage_render", fake_stage_render)

    result = tools.printlab_render(str(tmp_path), elevation=10.0, azimuth=20.0)

    assert result == "fake-report"
    assert len(captured["views"]) == 1
    (view,) = captured["views"]
    assert (view.label, view.elevation_deg, view.azimuth_deg) == ("custom", 10.0, 20.0)


def test_printlab_render_grid_layout_uses_engineering_view_default(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))
    captured = {}

    def fake_stage_render(stl_path, output_dir, *, views, layout, focus_center, focus_radius):
        captured["views"] = views
        captured["layout"] = layout
        return "fake-report"

    monkeypatch.setattr(pipeline, "stage_render", fake_stage_render)

    tools.printlab_render(str(tmp_path), layout="grid")

    assert captured["layout"] == "grid"
    assert captured["views"] == ["top", "front", "right", "iso"]


def test_printlab_render_forwards_focus_center_and_radius(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))
    captured = {}

    def fake_stage_render(stl_path, output_dir, *, views, layout, focus_center, focus_radius):
        captured["focus_center"] = focus_center
        captured["focus_radius"] = focus_radius
        return "fake-report"

    monkeypatch.setattr(pipeline, "stage_render", fake_stage_render)

    tools.printlab_render(str(tmp_path), focus_center=(1.0, 2.0, 3.0), focus_radius=5.0)

    assert captured["focus_center"] == (1.0, 2.0, 3.0)
    assert captured["focus_radius"] == 5.0


def test_printlab_init_scaffolds_toml_pointing_at_existing_module(tmp_path):
    (tmp_path / "part.py").write_text("def build():\n    ...\n")

    written = tools.printlab_init(str(tmp_path))

    assert Path(written) == tmp_path / "printlab.toml"
    config = pipeline.load_part_config(tmp_path, repo_root=tmp_path)
    assert config.name == tmp_path.name
    assert config.part_py == tmp_path / "part.py"
    assert config.build_function == "build"
    assert config.fea_load_case is None


def test_printlab_init_refuses_to_overwrite_existing_toml(tmp_path):
    (tmp_path / "part.py").write_text("def build():\n    ...\n")
    tools.printlab_init(str(tmp_path))

    with pytest.raises(pipeline.PipelineError):
        tools.printlab_init(str(tmp_path))


def test_printlab_init_refuses_missing_module(tmp_path):
    with pytest.raises(pipeline.PipelineError):
        tools.printlab_init(str(tmp_path))


def test_printlab_describe_reports_resolved_config(tmp_path):
    _write_config(tmp_path)

    described = tools.printlab_describe(str(tmp_path))

    assert described["name"] == "widget"
    assert described["part_py"] == str(tmp_path / "part.py")
    assert described["build_function"] == "build"
    assert described["fea_configured"] is False
    assert "output_dir_note" in described


def test_printlab_describe_reports_fea_configured(tmp_path):
    (tmp_path / "printlab.toml").write_text(
        _MINIMAL_CONFIG
        + "\n[fea]\n"
        "load_point_mm = [0.0, 0.0, 0.0]\n"
        "load_force_n = [0.0, 0.0, -1.0]\n"
        "load_region_radius_mm = 1.0\n"
    )

    described = tools.printlab_describe(str(tmp_path))

    assert described["fea_configured"] is True


def test_printlab_fea_missing_load_case_mentions_printlab_describe(tmp_path):
    _write_config(tmp_path)
    monkeypatch_dir = tmp_path / "output" / "check"
    monkeypatch_dir.mkdir(parents=True)
    (monkeypatch_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")

    with pytest.raises(pipeline.PipelineError, match="printlab_describe"):
        tools.printlab_fea(str(tmp_path))


def test_printlab_doctor_reports_repo_root():
    result = tools.printlab_doctor()
    assert "repo_root" in result
    assert Path(result["repo_root"]).is_absolute()
