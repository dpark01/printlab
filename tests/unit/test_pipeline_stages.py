"""Fast-lane unit tests for pipeline stages added/changed for issues #4/#5:
build_is_fresh (the fingerprint-based freshness check backing issue #5.1's
render-staleness fix), stage_fea_preview (issue #5.2), and stage_probe (issue
#5.3). stage_probe uses real cadquery/OCP (hard dependencies); stage_fea_preview
monkeypatches printlab.fea.mesh_runner so it never needs gmsh installed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import cadquery as cq
import pytest

from printlab import pipeline
from printlab.cad import CadBuildError, CadBuildResult, export_step, export_stl
from printlab.determinism import hash_file
from printlab.schemas import CadBuildReport


def _make_config(tmp_path: Path, *, build_function: str = "build") -> pipeline.PartConfig:
    part_py = tmp_path / "part.py"
    part_py.write_text("def build():\n    ...\n")
    return pipeline.PartConfig(
        name="widget",
        example_dir=tmp_path,
        source_path=part_py,
        printer_profile_path=tmp_path / "printer.yaml",
        material_profile_path=tmp_path / "material.yaml",
        process_profile_path=tmp_path / "process.yaml",
        build_function=build_function,
    )


def _fake_backend(*, dependencies=(), tool_versions=None):
    class FakeBackend:
        def tool_versions(self, request):
            return tool_versions or {}

        def build(self, request):
            shape = cq.Workplane("XY").box(1, 1, 1)
            return CadBuildResult(
                backend_name="cadquery",
                step_path=export_step(shape, request.output_dir / "part.step"),
                stl_path=export_stl(shape, request.output_dir / "part.stl"),
                dependencies=dependencies,
                tool_versions=tool_versions or {},
            )

    return FakeBackend()


class TestBuildIsFresh:
    def test_false_when_no_fingerprint_written_yet(self, tmp_path):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        assert pipeline.build_is_fresh(config, output_dir) is False

    def test_true_immediately_after_stage_build(self, tmp_path, monkeypatch):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        monkeypatch.setattr(pipeline, "get_cad_backend", lambda name: _fake_backend())
        pipeline.stage_build(config, output_dir)

        assert pipeline.build_is_fresh(config, output_dir) is True

    def test_false_after_cad_source_edited(self, tmp_path, monkeypatch):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(pipeline, "get_cad_backend", lambda name: _fake_backend())
        pipeline.stage_build(config, output_dir)

        config.part_py.write_text("def build():\n    pass  # edited\n")

        assert pipeline.build_is_fresh(config, output_dir) is False

    def test_false_when_build_function_differs(self, tmp_path, monkeypatch):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(pipeline, "get_cad_backend", lambda name: _fake_backend())
        pipeline.stage_build(config, output_dir)

        other_config = replace(config, build_function="build_closed")

        assert pipeline.build_is_fresh(other_config, output_dir) is False

    def test_false_when_part_py_missing(self, tmp_path):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / pipeline.ARTIFACT_FILENAMES["build_fingerprint"]).write_text(
            '{"cad_source_sha256": "x", "build_function": "build", "part_py": "x"}'
        )
        config.part_py.unlink()

        assert pipeline.build_is_fresh(config, output_dir) is False

    @pytest.mark.parametrize("malformed", ["[]", "null", '"value"'])
    def test_false_for_non_object_fingerprint(self, tmp_path, malformed):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / pipeline.ARTIFACT_FILENAMES["step"]).write_text("STEP")
        (output_dir / pipeline.ARTIFACT_FILENAMES["stl"]).write_text("STL")
        (output_dir / pipeline.ARTIFACT_FILENAMES["build_fingerprint"]).write_text(malformed)

        assert pipeline.build_is_fresh(config, output_dir) is False

    def test_false_when_step_is_missing(self, tmp_path, monkeypatch):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(pipeline, "get_cad_backend", lambda name: _fake_backend())
        pipeline.stage_build(config, output_dir)
        (output_dir / pipeline.ARTIFACT_FILENAMES["step"]).unlink()

        assert pipeline.build_is_fresh(config, output_dir) is False

    def test_false_after_dependency_is_edited(self, tmp_path, monkeypatch):
        config = _make_config(tmp_path)
        dependency = tmp_path / "included.scad"
        dependency.write_text("width = 10;\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        backend = _fake_backend(dependencies=(config.source_path, dependency), tool_versions={"cad": "1"})
        monkeypatch.setattr(pipeline, "get_cad_backend", lambda name: backend)
        pipeline.stage_build(config, output_dir)
        dependency.write_text("width = 11;\n")

        assert pipeline.build_is_fresh(config, output_dir) is False

    def test_false_after_backend_version_changes(self, tmp_path, monkeypatch):
        config = _make_config(tmp_path)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        monkeypatch.setattr(
            pipeline,
            "get_cad_backend",
            lambda name: _fake_backend(dependencies=(config.source_path,), tool_versions={"cad": "1"}),
        )
        pipeline.stage_build(config, output_dir)
        monkeypatch.setattr(
            pipeline,
            "get_cad_backend",
            lambda name: _fake_backend(dependencies=(config.source_path,), tool_versions={"cad": "2"}),
        )

        assert pipeline.build_is_fresh(config, output_dir) is False


def test_stage_build_writes_structured_error_report(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    class FailingBackend:
        def build(self, request):
            raise CadBuildError("translator failed", code="translation_failed", context={"exit": 2})

    monkeypatch.setattr(pipeline, "get_cad_backend", lambda name: FailingBackend())

    with pytest.raises(CadBuildError, match="translator failed"):
        pipeline.stage_build(config, output_dir)

    report = CadBuildReport.model_validate_json(
        (output_dir / pipeline.ARTIFACT_FILENAMES["cad_build_report"]).read_text()
    )
    assert report.status.value == "error"
    assert report.errors[0].code == "translation_failed"


class TestStageFeaPreview:
    def test_success_reports_node_and_element_counts(self, tmp_path, monkeypatch):
        import numpy as np

        def fake_run_mesh_worker(step_path, *, mesh_size_mm=None, timeout=300.0):
            return np.zeros((5, 3)), np.zeros((2, 4), dtype=np.int64), 1.5

        monkeypatch.setattr(pipeline.fea_mesh_runner, "run_mesh_worker", fake_run_mesh_worker)
        step_path = tmp_path / "part.step"
        step_path.write_text("ISO-10303-21;\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        report = pipeline.stage_fea_preview(step_path, output_dir, mesh_size_mm=None)

        assert report.status.value == "ok"
        assert report.mesh_node_count == 5
        assert report.mesh_element_count == 2
        assert report.resolved_mesh_size_mm == pytest.approx(1.5)
        assert (output_dir / pipeline.ARTIFACT_FILENAMES["fea_mesh_preview_report"]).is_file()

    def test_meshing_failure_reports_error_status_without_raising(self, tmp_path, monkeypatch):
        def fake_run_mesh_worker(step_path, *, mesh_size_mm=None, timeout=300.0):
            raise RuntimeError("Invalid boundary mesh (overlapping facets) on surface 9")

        monkeypatch.setattr(pipeline.fea_mesh_runner, "run_mesh_worker", fake_run_mesh_worker)
        step_path = tmp_path / "part.step"
        step_path.write_text("ISO-10303-21;\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        report = pipeline.stage_fea_preview(step_path, output_dir, mesh_size_mm=4.85)

        assert report.status.value == "error"
        assert report.mesh_node_count is None
        assert report.mesh_element_count is None
        assert any("Invalid boundary mesh" in err.message for err in report.errors)
        assert (output_dir / pipeline.ARTIFACT_FILENAMES["fea_mesh_preview_report"]).is_file()

    def test_missing_gmsh_reports_error_status_without_raising(self, tmp_path, monkeypatch):
        def fake_run_mesh_worker(step_path, *, mesh_size_mm=None, timeout=300.0):
            raise ModuleNotFoundError("the `gmsh` package is not installed")

        monkeypatch.setattr(pipeline.fea_mesh_runner, "run_mesh_worker", fake_run_mesh_worker)
        step_path = tmp_path / "part.step"
        step_path.write_text("ISO-10303-21;\n")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        report = pipeline.stage_fea_preview(step_path, output_dir)

        assert report.status.value == "error"


class TestStageProbe:
    def test_classifies_points_and_writes_report(self, tmp_path):
        box = cq.Workplane("XY").box(10, 10, 10)
        step_path = export_step(box, tmp_path / "part.step")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        report = pipeline.stage_probe(
            step_path,
            output_dir,
            points=[(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)],
            tolerance_mm=1e-6,
        )

        assert report.input_sha256 == hash_file(step_path)
        assert [p.classification for p in report.points] == ["IN", "OUT"]
        assert (output_dir / pipeline.ARTIFACT_FILENAMES["probe_report"]).is_file()
