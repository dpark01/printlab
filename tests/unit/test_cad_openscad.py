from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cadquery as cq
import pytest
import trimesh

from printlab.cad import CadBuildError, CadBuildRequest
from printlab.cad import openscad as openscad_module
from printlab.cad.openscad import OpenSCADBackend


def _request(tmp_path: Path, *, options: dict | None = None) -> CadBuildRequest:
    source = tmp_path / "part.scad"
    source.write_text("cube([10, 20, 30]);\n")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return CadBuildRequest(source_path=source, output_dir=output_dir, options=options or {})


def _successful_run(calls: list):
    def run(command, *, cwd, timeout, env=None, script_path=None):
        calls.append((command, cwd, timeout, env, script_path))
        if Path(command[0]).name == "openscad":
            output_indices = [index + 1 for index, value in enumerate(command) if value == "-o"]
            Path(command[output_indices[0]]).write_text("group() { cube(size = [10, 20, 30]); }\n")
            Path(command[output_indices[1]]).write_text("solid reference\nendsolid reference\n")
            dependency_path = Path(command[command.index("-d") + 1])
            dependency_path.write_text(f"part.csg: {cwd / 'part.scad'}\n")
        else:
            assert env is not None
            Path(env["PRINTLAB_STEP_PATH"]).write_text("ISO-10303-21;\n")
            Path(env["PRINTLAB_BRIDGE_METADATA_PATH"]).write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "fallback_objects": [],
                        "solid_count": 1,
                        "volume_mm3": 6000.0,
                        "face_count": 6,
                    }
                )
            )

    return run


def _patch_success(monkeypatch, calls: list) -> None:
    monkeypatch.setattr(openscad_module, "find_openscad_binary", lambda explicit=None: Path("/bin/openscad"))
    monkeypatch.setattr(
        openscad_module, "find_freecadcmd_binary", lambda explicit=None: Path("/bin/FreeCADCmd")
    )
    monkeypatch.setattr(openscad_module, "detect_binary_version", lambda binary: f"{binary.name} 1.0")
    monkeypatch.setattr(openscad_module, "_run", _successful_run(calls))
    monkeypatch.setattr(
        openscad_module,
        "_run_bridge",
        lambda command, **kwargs: (
            _successful_run(calls)(command, **kwargs)
            or subprocess.CompletedProcess(command, 0, "", "")
        ),
    )
    monkeypatch.setattr(
        openscad_module.cq.importers,
        "importStep",
        lambda path: cq.Workplane("XY").box(10, 20, 30),
    )

    def fake_export_stl(shape, path):
        Path(path).write_text("solid candidate\nendsolid candidate\n")
        return Path(path)

    monkeypatch.setattr(openscad_module, "export_stl", fake_export_stl)
    monkeypatch.setattr(
        openscad_module,
        "_compare_geometry",
        lambda reference, candidate: {
            "reference_watertight": True,
            "candidate_watertight": True,
            "reference_components": 1,
            "candidate_components": 1,
            "max_surface_deviation_mm": 0.0,
            "relative_volume_delta": 0.0,
            "max_bbox_delta_mm": 0.0,
        },
    )


def test_build_runs_openscad_then_freecad_and_emits_step_stl(tmp_path: Path, monkeypatch) -> None:
    calls = []
    _patch_success(monkeypatch, calls)
    request = _request(tmp_path, options={"defines": {"width": 12, "label": "A"}})

    result = OpenSCADBackend().build(request)

    assert result.step_path.read_text() == "ISO-10303-21;\n"
    assert result.stl_path.read_text() == "solid candidate\nendsolid candidate\n"
    assert result.dependencies == (request.source_path.resolve(),)
    assert result.tool_versions == {"openscad": "openscad 1.0", "freecad": "FreeCADCmd 1.0"}
    openscad_command = calls[0][0]
    assert openscad_command[-1] == str(request.source_path.resolve())
    assert ["-D", 'label="A"'] == openscad_command[openscad_command.index("-D") :][:2]
    assert ["-D", "width=12"] == openscad_command[openscad_command.index("-D", 4) :][-3:-1]
    assert calls[1][4].name == "freecad_bridge.py"
    assert "--user-cfg" in calls[1][0]
    assert calls[1][3]["FREECAD_USER_HOME"].endswith("freecad-home")


def test_build_rejects_freecad_mesh_fallback(tmp_path: Path, monkeypatch) -> None:
    calls = []
    _patch_success(monkeypatch, calls)
    original_run = openscad_module._run_bridge

    def run_with_fallback(command, *, script_path, cwd, timeout, env):
        result = original_run(command, script_path=script_path, cwd=cwd, timeout=timeout, env=env)
        Path(env["PRINTLAB_BRIDGE_METADATA_PATH"]).write_text(
            json.dumps(
                {
                    "status": "ok",
                    "fallback_objects": [{"name": "hull", "proxy": "CGALFeature"}],
                }
            )
        )
        return result

    monkeypatch.setattr(openscad_module, "_run_bridge", run_with_fallback)

    with pytest.raises(CadBuildError, match="mesh or unsupported fallback") as exc_info:
        OpenSCADBackend().build(_request(tmp_path))

    assert exc_info.value.code == "non_brep_fallback"


def test_build_surfaces_freecad_bridge_metadata_on_failure(tmp_path: Path, monkeypatch) -> None:
    calls = []
    _patch_success(monkeypatch, calls)

    def failed_bridge(command, *, script_path, cwd, timeout, env):
        Path(env["PRINTLAB_BRIDGE_METADATA_PATH"]).write_text(
            json.dumps({"status": "error", "error": "invalid CSG token"})
        )
        return subprocess.CompletedProcess(command, 1, "", "parser failed")

    monkeypatch.setattr(openscad_module, "_run_bridge", failed_bridge)

    with pytest.raises(CadBuildError, match="invalid CSG token") as exc_info:
        OpenSCADBackend().build(_request(tmp_path))

    assert exc_info.value.code == "freecad_bridge_failed"


def test_build_reports_missing_binaries(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(openscad_module, "find_openscad_binary", lambda explicit=None: None)
    monkeypatch.setattr(openscad_module, "find_freecadcmd_binary", lambda explicit=None: None)

    with pytest.raises(CadBuildError, match="openscad, FreeCADCmd") as exc_info:
        OpenSCADBackend().build(_request(tmp_path))

    assert exc_info.value.code == "binary_not_found"


def test_run_translates_timeout_to_structured_error(tmp_path: Path, monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr(openscad_module.subprocess, "run", timeout)

    with pytest.raises(CadBuildError) as exc_info:
        openscad_module._run(["openscad"], cwd=tmp_path, timeout=1)

    assert exc_info.value.code == "cad_build_timeout"


def test_run_bridge_executes_script_through_freecad_stdin(tmp_path: Path, monkeypatch) -> None:
    script_path = tmp_path / "bridge.py"
    script_path.write_text("print('bridge ran')\n")
    captured = {}

    def run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(openscad_module.subprocess, "run", run)

    openscad_module._run_bridge(
        ["FreeCADCmd", "--user-cfg", "user.cfg"],
        script_path=script_path,
        cwd=tmp_path,
        timeout=10,
        env={},
    )

    assert "exec(compile(open(" in captured["input"]
    assert str(script_path) in captured["input"]


def test_geometry_comparison_welds_stl_vertices(tmp_path: Path) -> None:
    reference = tmp_path / "reference.stl"
    candidate = tmp_path / "candidate.stl"
    mesh = trimesh.creation.box(extents=(10, 20, 30))
    mesh.export(reference)
    mesh.export(candidate)

    comparison = openscad_module._compare_geometry(reference, candidate)

    assert comparison["reference_watertight"] is True
    assert comparison["candidate_watertight"] is True
    assert comparison["reference_components"] == 1
    assert comparison["candidate_components"] == 1


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("OpenSCAD version 2021.01\n", "2021.01"),
        ("OpenSCAD version 2026.06.12\n", "2026.06.12"),
        ("FreeCAD 1.1.1, Libs: 1.1.1R12345 (Git)\n", "1.1.1"),
    ],
)
def test_detect_binary_version_normalizes_native_output(output, expected, monkeypatch) -> None:
    monkeypatch.setattr(
        openscad_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, output, ""),
    )

    assert openscad_module.detect_binary_version(Path("/bin/tool")) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, "true"), (3.5, "3.5"), ("A", '"A"'), ([1, False], "[1, false]")],
)
def test_serialize_define(value, expected) -> None:
    assert openscad_module._serialize_define(value) == expected
