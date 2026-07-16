"""Fast-lane tests for printlab_mcp.tools.

Imports only printlab_mcp.tools (never fastmcp), so it runs in CI's fast lane
with no MCP install. `stage_build` is monkeypatched so these never invoke the
CAD kernel -- the real CadQuery-backed end-to-end check lives in
tests/integration/test_mcp_smoke.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from printlab import pipeline
from printlab.determinism import hash_file
from printlab.schemas import PrintabilityCheck, PrintabilityReport
from printlab.schemas.common import Status
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
        pipeline._write_json_atomic_raw(
            output_dir / pipeline.ARTIFACT_FILENAMES["build_fingerprint"],
            {
                "cad_backend": config.cad_backend,
                "cad_source_sha256": f"fake-hash-for-{config.build_function}",
                "build_function": config.build_function,
                "source_path": str(config.source_path),
            },
        )
        return step, stl

    return build


def test_ensure_built_builds_when_missing(tmp_path, monkeypatch):
    _write_config(tmp_path)
    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))

    config, output_dir, rebuilt = tools.ensure_built(tmp_path, "check")

    assert len(calls) == 1
    assert rebuilt is True
    assert config.name == "widget"
    assert output_dir == pipeline.default_output_dir(config, "check")
    assert (output_dir / "part.stl").is_file()


def test_ensure_built_skips_when_fresh(tmp_path, monkeypatch):
    _write_config(tmp_path)
    (tmp_path / "part.py").write_text("def build():\n    ...\n")
    output_dir = tmp_path / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")
    (output_dir / pipeline.ARTIFACT_FILENAMES["step"]).write_text("ISO-10303-21;\n")
    # build_is_fresh compares against the CAD module's *current* content hash,
    # so the fingerprint has to be computed from a real part.py on disk (not
    # the fake-hash shortcut _write_fresh_fingerprint/_fake_build use).
    config = pipeline.load_part_config(tmp_path)
    (output_dir / pipeline.ARTIFACT_FILENAMES["build_fingerprint"]).write_text(
        json.dumps(
            pipeline._build_fingerprint(config)
        )
    )

    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))

    _config, _output_dir, rebuilt = tools.ensure_built(tmp_path, "check")

    assert calls == []
    assert rebuilt is False


def test_ensure_built_rebuilds_stale_build_even_if_stl_present(tmp_path, monkeypatch):
    """Regression test for issue #5.1: printlab_render (and friends) used to
    treat a present part.stl as sufficient to skip rebuilding, so an edited
    CAD source (or, per test below, a switched build function) was silently
    ignored and a stale artifact reused."""
    _write_config(tmp_path)
    output_dir = tmp_path / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")
    (output_dir / pipeline.ARTIFACT_FILENAMES["step"]).write_text("ISO-10303-21;\n")
    # No build_fingerprint.json written -- simulates a build from before this
    # fix, or a stale/foreign output dir.

    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))

    _config, _output_dir, rebuilt = tools.ensure_built(tmp_path, "check")

    assert calls == [output_dir]
    assert rebuilt is True


def test_ensure_built_rebuilds_when_function_override_differs_from_recorded_build(tmp_path, monkeypatch):
    _write_config(tmp_path)
    (tmp_path / "part.py").write_text("def build():\n    ...\ndef build_closed():\n    ...\n")
    output_dir = tmp_path / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")
    config = pipeline.load_part_config(tmp_path)
    (output_dir / pipeline.ARTIFACT_FILENAMES["build_fingerprint"]).write_text(
        json.dumps(
            {
                "cad_backend": config.cad_backend,
                "cad_source_sha256": hash_file(config.part_py),
                "build_function": "build",
                "source_path": str(config.source_path),
            }
        )
    )

    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))

    _config, _output_dir, rebuilt = tools.ensure_built(tmp_path, "check", function="build_closed")

    assert calls == [output_dir]
    assert rebuilt is True


def test_ensure_built_respects_output_dir_override(tmp_path, monkeypatch):
    _write_config(tmp_path)
    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))
    override_dir = tmp_path / "scratch"

    _config, resolved_output_dir, rebuilt = tools.ensure_built(tmp_path, "check", output_dir=override_dir)

    assert resolved_output_dir == override_dir
    assert calls == [override_dir]
    assert rebuilt is True
    assert (override_dir / "part.stl").is_file()


@pytest.mark.parametrize("func", [tools.printlab_check, tools.printlab_orient, tools.printlab_render])
def test_bogus_example_dir_raises_pipeline_error(func, tmp_path):
    with pytest.raises(pipeline.PipelineError):
        func(str(tmp_path / "does_not_exist"))


def test_printlab_check_forwards_output_dir(tmp_path, monkeypatch):
    captured = {}

    def fake_run_check(example_dir, *, output_dir=None, build_function=None):
        captured["output_dir"] = output_dir
        captured["build_function"] = build_function
        return {"printability": "fake-report"}

    monkeypatch.setattr(pipeline, "run_check", fake_run_check)

    override_dir = tmp_path / "scratch"
    result = tools.printlab_check(str(tmp_path), output_dir=str(override_dir))

    assert result == "fake-report"
    assert captured["output_dir"] == override_dir
    assert captured["build_function"] is None


def test_printlab_check_forwards_function_override(tmp_path, monkeypatch):
    captured = {}

    def fake_run_check(example_dir, *, output_dir=None, build_function=None):
        captured["build_function"] = build_function
        return {"printability": "fake-report"}

    monkeypatch.setattr(pipeline, "run_check", fake_run_check)

    tools.printlab_check(str(tmp_path), function="build_closed")

    assert captured["build_function"] == "build_closed"


def test_printlab_all_forwards_output_dir_and_backend(tmp_path, monkeypatch):
    captured = {}

    def fake_run_all(example_dir, backend, *, output_dir=None, build_function=None):
        captured["backend"] = backend
        captured["output_dir"] = output_dir
        captured["build_function"] = build_function
        return {"printability": "fake-report"}

    monkeypatch.setattr(pipeline, "run_all", fake_run_all)

    override_dir = tmp_path / "scratch"
    result = tools.printlab_all(str(tmp_path), backend="prusaslicer", output_dir=str(override_dir))

    assert result == "fake-report"
    assert captured["backend"] == "prusaslicer"
    assert captured["output_dir"] == override_dir
    assert captured["build_function"] is None


def test_printlab_render_elevation_and_azimuth_build_custom_view(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))
    captured = {}

    def fake_stage_render(stl_path, output_dir, *, views, layout, focus_center, focus_radius, rebuilt):
        captured["views"] = views
        captured["rebuilt"] = rebuilt
        return "fake-report"

    monkeypatch.setattr(pipeline, "stage_render", fake_stage_render)

    result = tools.printlab_render(str(tmp_path), elevation=10.0, azimuth=20.0)

    assert result == "fake-report"
    assert captured["rebuilt"] is True
    assert len(captured["views"]) == 1
    (view,) = captured["views"]
    assert (view.label, view.elevation_deg, view.azimuth_deg) == ("custom", 10.0, 20.0)


def test_printlab_render_grid_layout_uses_engineering_view_default(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))
    captured = {}

    def fake_stage_render(stl_path, output_dir, *, views, layout, focus_center, focus_radius, rebuilt):
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

    def fake_stage_render(stl_path, output_dir, *, views, layout, focus_center, focus_radius, rebuilt):
        captured["focus_center"] = focus_center
        captured["focus_radius"] = focus_radius
        return "fake-report"

    monkeypatch.setattr(pipeline, "stage_render", fake_stage_render)

    tools.printlab_render(str(tmp_path), focus_center=(1.0, 2.0, 3.0), focus_radius=5.0)

    assert captured["focus_center"] == (1.0, 2.0, 3.0)
    assert captured["focus_radius"] == 5.0


def test_printlab_render_reports_rebuilt_false_when_build_is_fresh(tmp_path, monkeypatch):
    _write_config(tmp_path)
    (tmp_path / "part.py").write_text("def build():\n    ...\n")
    output_dir = tmp_path / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")
    (output_dir / pipeline.ARTIFACT_FILENAMES["step"]).write_text("ISO-10303-21;\n")
    config = pipeline.load_part_config(tmp_path)
    (output_dir / pipeline.ARTIFACT_FILENAMES["build_fingerprint"]).write_text(
        json.dumps(
            pipeline._build_fingerprint(config)
        )
    )
    calls: list = []
    monkeypatch.setattr(pipeline, "stage_build", _fake_build(calls))
    captured = {}

    def fake_stage_render(stl_path, output_dir, *, views, layout, focus_center, focus_radius, rebuilt):
        captured["rebuilt"] = rebuilt
        return "fake-report"

    monkeypatch.setattr(pipeline, "stage_render", fake_stage_render)

    tools.printlab_render(str(tmp_path))

    assert calls == []
    assert captured["rebuilt"] is False


def test_printlab_orient_forwards_function_to_ensure_built(tmp_path, monkeypatch):
    captured = {}

    # ensure_built's real return is (config, output_dir, rebuilt); orient only
    # ever reads output_dir from it, so the other two can be stubbed loosely.
    def fake_ensure_built(example_dir, backend, *, output_dir=None, function=None):
        captured["function"] = function
        return None, tmp_path, False

    monkeypatch.setattr(tools, "ensure_built", fake_ensure_built)
    monkeypatch.setattr(pipeline, "stage_orientation_search", lambda stl_path, output_dir: "fake-report")

    result = tools.printlab_orient(str(tmp_path), function="build_closed")

    assert result == "fake-report"
    assert captured["function"] == "build_closed"


def test_printlab_fea_forwards_function_to_ensure_built(tmp_path, monkeypatch):
    _write_config(tmp_path)
    captured = {}

    def fake_ensure_built(example_dir, backend, *, output_dir=None, function=None):
        captured["function"] = function
        return pipeline.load_part_config(tmp_path), tmp_path, False

    monkeypatch.setattr(tools, "ensure_built", fake_ensure_built)

    with pytest.raises(pipeline.PipelineError, match="printlab_describe"):
        tools.printlab_fea(str(tmp_path), function="build_closed")

    assert captured["function"] == "build_closed"


def test_printlab_init_scaffolds_toml_pointing_at_existing_module(tmp_path):
    (tmp_path / "part.py").write_text("def build():\n    ...\n")

    written = tools.printlab_init(str(tmp_path))

    assert Path(written) == tmp_path / "printlab.toml"
    config = pipeline.load_part_config(tmp_path, repo_root=tmp_path)
    assert config.name == tmp_path.name
    assert config.part_py == tmp_path / "part.py"
    assert config.build_function == "build"
    assert config.fea_load_case is None


def test_printlab_init_scaffolds_openscad_source(tmp_path):
    (tmp_path / "part.scad").write_text("cube([1, 1, 1]);\n")

    written = tools.printlab_init(str(tmp_path), source="part.scad", cad_backend="openscad")

    assert Path(written) == tmp_path / "printlab.toml"
    config = pipeline.load_part_config(tmp_path, repo_root=tmp_path)
    assert config.cad_backend == "openscad"
    assert config.source_path == tmp_path / "part.scad"
    assert config.build_function is None


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
    assert described["cad_backend"] == "cadquery"
    assert described["source_path"] == str(tmp_path / "part.py")
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


def test_printlab_fea_missing_load_case_mentions_printlab_describe(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))

    with pytest.raises(pipeline.PipelineError, match="printlab_describe"):
        tools.printlab_fea(str(tmp_path))


def test_printlab_fea_preview_does_not_require_fea_load_case(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))
    captured = {}

    def fake_stage_fea_preview(step_path, output_dir, *, mesh_size_mm=None):
        captured["mesh_size_mm"] = mesh_size_mm
        return "fake-preview-report"

    monkeypatch.setattr(pipeline, "stage_fea_preview", fake_stage_fea_preview)

    result = tools.printlab_fea_preview(str(tmp_path), mesh_size_mm=0.25)

    assert result == "fake-preview-report"
    assert captured["mesh_size_mm"] == 0.25


def test_printlab_probe_forwards_points_and_tolerance(tmp_path, monkeypatch):
    _write_config(tmp_path)
    monkeypatch.setattr(pipeline, "stage_build", _fake_build([]))
    captured = {}

    def fake_stage_probe(step_path, output_dir, *, points, tolerance_mm):
        captured["points"] = points
        captured["tolerance_mm"] = tolerance_mm
        return "fake-probe-report"

    monkeypatch.setattr(pipeline, "stage_probe", fake_stage_probe)

    points = [(0.0, 0.0, 0.0), (10.0, 10.0, 10.0)]
    result = tools.printlab_probe(str(tmp_path), points, tolerance_mm=0.01)

    assert result == "fake-probe-report"
    assert captured["points"] == points
    assert captured["tolerance_mm"] == 0.01


def test_printlab_export_copies_default_formats_and_warns_on_missing(tmp_path):
    example_dir = tmp_path / "example"
    example_dir.mkdir()
    _write_config(example_dir)
    output_dir = example_dir / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")
    (output_dir / pipeline.ARTIFACT_FILENAMES["step"]).write_text("ISO-10303-21;\n")

    dest_dir = tmp_path / "deliverables"
    report = tools.printlab_export(str(example_dir), "check", str(dest_dir))

    assert report.status == Status.OK
    assert {e.format for e in report.exported} == {"stl", "step"}
    assert (dest_dir / "widget.stl").is_file()
    assert (dest_dir / "widget.step").is_file()


def test_printlab_export_warns_on_missing_requested_format(tmp_path):
    example_dir = tmp_path / "example"
    example_dir.mkdir()
    _write_config(example_dir)
    output_dir = example_dir / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")

    dest_dir = tmp_path / "deliverables"
    report = tools.printlab_export(str(example_dir), "check", str(dest_dir), formats=["stl", "gcode"])

    assert report.status == Status.WARNING
    assert {e.format for e in report.exported} == {"stl"}
    assert any(err.code == "export_source_missing" for err in report.errors)


def test_printlab_export_uses_name_prefix(tmp_path):
    example_dir = tmp_path / "example"
    example_dir.mkdir()
    _write_config(example_dir)
    output_dir = example_dir / "output" / "check"
    output_dir.mkdir(parents=True)
    (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("solid x\nendsolid x\n")

    dest_dir = tmp_path / "deliverables"
    report = tools.printlab_export(
        str(example_dir), "check", str(dest_dir), formats=["stl"], name_prefix="mypart_v2"
    )

    assert report.status == Status.OK
    assert (dest_dir / "mypart_v2.stl").is_file()


def _write_printability_report(path: Path, *, metrics: dict, checks: list[PrintabilityCheck]) -> None:
    report = PrintabilityReport(metrics=metrics, checks=checks)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json())


def test_printlab_diff_reports_numeric_metric_deltas_and_check_transitions(tmp_path):
    report_a_path = tmp_path / "a" / "printability_report.json"
    report_b_path = tmp_path / "b" / "printability_report.json"
    _write_printability_report(
        report_a_path,
        metrics={"filament_mass_g": 10.0, "layer_count": 50, "manifold": True, "note": "x"},
        checks=[PrintabilityCheck(name="wall_thickness", status=Status.ERROR, message="too thin")],
    )
    _write_printability_report(
        report_b_path,
        metrics={"filament_mass_g": 12.5, "layer_count": 50, "manifold": False, "note": "y"},
        checks=[PrintabilityCheck(name="wall_thickness", status=Status.OK, message="fixed")],
    )

    diff = tools.printlab_diff(str(report_a_path), str(report_b_path))

    deltas_by_metric = {d.metric: d for d in diff.metric_deltas}
    assert "layer_count" not in deltas_by_metric  # unchanged -- must not appear
    assert deltas_by_metric["filament_mass_g"].delta == pytest.approx(2.5)
    assert deltas_by_metric["manifold"].delta is None  # bool, not numeric
    assert deltas_by_metric["note"].delta is None  # string, not numeric

    assert len(diff.check_changes) == 1
    change = diff.check_changes[0]
    assert change.name == "wall_thickness"
    assert change.status_a == Status.ERROR
    assert change.status_b == Status.OK


def test_printlab_diff_accepts_directory_paths(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    _write_printability_report(dir_a / "printability_report.json", metrics={}, checks=[])
    _write_printability_report(dir_b / "printability_report.json", metrics={}, checks=[])

    diff = tools.printlab_diff(str(dir_a), str(dir_b))

    assert diff.metric_deltas == []
    assert diff.check_changes == []


def test_printlab_doctor_reports_repo_root():
    result = tools.printlab_doctor()
    assert "repo_root" in result
    assert Path(result["repo_root"]).is_absolute()
    assert {tool["tool"] for tool in result["cad_tools"]} == {"openscad", "freecad"}
