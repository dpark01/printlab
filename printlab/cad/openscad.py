"""Strict OpenSCAD -> FreeCAD B-rep STEP backend."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
import trimesh

from printlab.cad.backend import export_stl
from printlab.cad.base import CadBackend, CadBuildError, CadBuildRequest, CadBuildResult

DEFAULT_TIMEOUT_S = 300.0
DEFAULT_MAX_SURFACE_DEVIATION_MM = 0.2
DEFAULT_MAX_RELATIVE_VOLUME_DELTA = 0.005
DEFAULT_MAX_BBOX_DELTA_MM = 0.1

_OPENSCAD_CANDIDATES = (
    "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD",
)
_FREECAD_CANDIDATES = (
    "/Applications/FreeCAD.app/Contents/Resources/bin/FreeCADCmd",
    "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd",
    "/Applications/FreeCAD.app/Contents/MacOS/FreeCADCmd",
    "/Applications/FreeCAD.app/Contents/MacOS/freecadcmd",
)


def find_openscad_binary(explicit: str | None = None) -> Path | None:
    return _find_binary(explicit, ("openscad",), _OPENSCAD_CANDIDATES)


def find_freecadcmd_binary(explicit: str | None = None) -> Path | None:
    return _find_binary(explicit, ("FreeCADCmd", "freecadcmd"), _FREECAD_CANDIDATES)


def _find_binary(explicit: str | None, names: tuple[str, ...], candidates: tuple[str, ...]) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def detect_binary_version(binary: Path, *, timeout: float = 10.0) -> str:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CadBuildError(
            f"could not query {binary.name} version: {exc}",
            code="version_detection_failed",
            context={"binary": str(binary)},
        ) from exc
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode != 0 or not output:
        raise CadBuildError(
            f"could not query {binary.name} version",
            code="version_detection_failed",
            context={"binary": str(binary), "returncode": result.returncode},
        )
    for pattern in (r"OpenSCAD version\s+([^\s]+)", r"FreeCAD\s+([^,\s]+)"):
        match = re.search(pattern, output, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return output.splitlines()[0]


def detect_openscad_toolchain() -> dict[str, dict[str, str | bool | None]]:
    """Report the two native tools required by the OpenSCAD backend."""
    detected: dict[str, dict[str, str | bool | None]] = {}
    for name, finder in (("openscad", find_openscad_binary), ("freecad", find_freecadcmd_binary)):
        binary = finder()
        if binary is None:
            detected[name] = {"available": False, "version": None, "binary": None, "notes": "not found"}
            continue
        try:
            version = detect_binary_version(binary)
            notes = ""
        except CadBuildError as exc:
            version = None
            notes = str(exc)
        detected[name] = {
            "available": True,
            "version": version,
            "binary": str(binary),
            "notes": notes,
        }
    return detected


def _serialize_define(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_serialize_define(item) for item in value) + "]"
    raise CadBuildError(
        f"unsupported OpenSCAD define value {value!r}",
        code="invalid_openscad_define",
    )


def _run(command: list[str], *, cwd: Path, timeout: float, env: dict[str, str] | None = None) -> None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CadBuildError(
            f"CAD subprocess timed out after {timeout:g}s",
            code="cad_build_timeout",
            context={"command": command, "timeout_s": timeout},
        ) from exc
    except OSError as exc:
        raise CadBuildError(
            f"could not execute {command[0]}: {exc}",
            code="binary_execution_failed",
            context={"command": command},
        ) from exc
    if result.returncode != 0:
        raise CadBuildError(
            f"CAD subprocess failed: {(result.stderr or result.stdout).strip()}",
            code="cad_subprocess_failed",
            context={"command": command, "returncode": result.returncode},
        )


def _run_bridge(
    command: list[str], *, script_path: Path, cwd: Path, timeout: float, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    script = (
        f"exec(compile(open({str(script_path)!r}, encoding='utf-8').read(), "
        f"{str(script_path)!r}, 'exec'))\n"
    )
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CadBuildError(
            f"FreeCAD bridge timed out after {timeout:g}s",
            code="cad_build_timeout",
            context={"command": command, "timeout_s": timeout},
        ) from exc
    except OSError as exc:
        raise CadBuildError(
            f"could not execute {command[0]}: {exc}",
            code="binary_execution_failed",
            context={"command": command},
        ) from exc


def _parse_dependencies(path: Path, source_dir: Path, source_path: Path) -> tuple[Path, ...]:
    dependencies = {source_path.resolve()}
    if not path.is_file():
        return tuple(sorted(dependencies))
    text = path.read_text().replace("\\\n", " ")
    for line in text.splitlines():
        if ":" not in line:
            continue
        _, values = line.split(":", 1)
        for value in shlex.split(values):
            dependency = Path(value)
            if not dependency.is_absolute():
                dependency = source_dir / dependency
            if dependency.is_file():
                dependencies.add(dependency.resolve())
    return tuple(sorted(dependencies))


def _load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(path, force="mesh", process=True)
    if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty:
        raise CadBuildError(f"invalid or empty mesh: {path}", code="invalid_mesh")
    return mesh


def _compare_geometry(reference_path: Path, candidate_path: Path) -> dict[str, Any]:
    reference = _load_mesh(reference_path)
    candidate = _load_mesh(candidate_path)
    reference_points = np.vstack((reference.vertices, reference.triangles_center))
    candidate_points = np.vstack((candidate.vertices, candidate.triangles_center))
    _, reference_distances, _ = trimesh.proximity.closest_point(candidate, reference_points)
    _, candidate_distances, _ = trimesh.proximity.closest_point(reference, candidate_points)
    reference_volume = abs(float(reference.volume))
    candidate_volume = abs(float(candidate.volume))
    volume_denominator = max(reference_volume, candidate_volume, 1e-12)
    return {
        "reference_watertight": bool(reference.is_watertight),
        "candidate_watertight": bool(candidate.is_watertight),
        "reference_components": len(reference.split(only_watertight=False)),
        "candidate_components": len(candidate.split(only_watertight=False)),
        "max_surface_deviation_mm": max(
            float(np.max(reference_distances)), float(np.max(candidate_distances))
        ),
        "relative_volume_delta": abs(reference_volume - candidate_volume) / volume_denominator,
        "max_bbox_delta_mm": float(np.max(np.abs(reference.bounds - candidate.bounds))),
    }


class OpenSCADBackend(CadBackend):
    name = "openscad"

    def tool_versions(self, request: CadBuildRequest) -> dict[str, str]:
        options = dict(request.options)
        openscad = find_openscad_binary(options.get("openscad_binary"))
        freecadcmd = find_freecadcmd_binary(options.get("freecadcmd_binary"))
        missing = [
            name
            for name, binary in (("openscad", openscad), ("FreeCADCmd", freecadcmd))
            if binary is None
        ]
        if missing:
            raise CadBuildError(
                f"required CAD binaries not found: {', '.join(missing)}",
                code="binary_not_found",
                context={"missing": missing},
            )
        assert openscad is not None and freecadcmd is not None
        return {
            "openscad": detect_binary_version(openscad),
            "freecad": detect_binary_version(freecadcmd),
        }

    def build(self, request: CadBuildRequest) -> CadBuildResult:
        source_path = request.source_path.resolve()
        if request.build_target is not None:
            raise CadBuildError(
                "OpenSCAD does not support a Python build function",
                code="unsupported_build_target",
            )
        if not source_path.is_file():
            raise CadBuildError(f"OpenSCAD source not found: {source_path}", code="source_not_found")
        if source_path.suffix.lower() != ".scad":
            raise CadBuildError(f"OpenSCAD source must end in .scad: {source_path}", code="invalid_source")

        options = dict(request.options)
        openscad = find_openscad_binary(options.get("openscad_binary"))
        freecadcmd = find_freecadcmd_binary(options.get("freecadcmd_binary"))
        missing = [
            name
            for name, binary in (("openscad", openscad), ("FreeCADCmd", freecadcmd))
            if binary is None
        ]
        if missing:
            raise CadBuildError(
                f"required CAD binaries not found: {', '.join(missing)}",
                code="binary_not_found",
                context={"missing": missing},
            )
        assert openscad is not None and freecadcmd is not None

        timeout = float(options.get("timeout_s", DEFAULT_TIMEOUT_S))
        defines = options.get("defines", {})
        if not isinstance(defines, dict):
            raise CadBuildError("OpenSCAD `defines` must be a table", code="invalid_openscad_define")
        settings = {
            "defines": defines,
            "timeout_s": timeout,
            "max_surface_deviation_mm": float(
                options.get("max_surface_deviation_mm", DEFAULT_MAX_SURFACE_DEVIATION_MM)
            ),
            "max_relative_volume_delta": float(
                options.get("max_relative_volume_delta", DEFAULT_MAX_RELATIVE_VOLUME_DELTA)
            ),
            "max_bbox_delta_mm": float(options.get("max_bbox_delta_mm", DEFAULT_MAX_BBOX_DELTA_MM)),
        }

        request.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="printlab-openscad-", dir=request.output_dir) as temp_name:
            temp_dir = Path(temp_name)
            csg_path = temp_dir / "part.csg"
            reference_stl = temp_dir / "reference.stl"
            dependency_path = temp_dir / "dependencies.d"
            temporary_step = temp_dir / "part.step"
            temporary_stl = temp_dir / "part.stl"
            bridge_metadata_path = temp_dir / "bridge.json"

            openscad_command = [
                str(openscad),
                "--hardwarnings",
                "-d",
                str(dependency_path),
                "-o",
                str(csg_path),
                "-o",
                str(reference_stl),
            ]
            for name in sorted(defines):
                openscad_command.extend(("-D", f"{name}={_serialize_define(defines[name])}"))
            openscad_command.append(str(source_path))
            _run(openscad_command, cwd=source_path.parent, timeout=timeout)
            for produced in (csg_path, reference_stl):
                if not produced.is_file() or produced.stat().st_size == 0:
                    raise CadBuildError(
                        f"OpenSCAD did not produce {produced.name}",
                        code="missing_cad_output",
                    )

            freecad_user_home = temp_dir / "freecad-home"
            freecad_user_home.mkdir()
            bridge_env = os.environ.copy()
            bridge_env.update(
                {
                    "FREECAD_USER_HOME": str(freecad_user_home),
                    "PRINTLAB_CSG_PATH": str(csg_path),
                    "PRINTLAB_STEP_PATH": str(temporary_step),
                    "PRINTLAB_BRIDGE_METADATA_PATH": str(bridge_metadata_path),
                }
            )
            bridge_script = Path(__file__).with_name("freecad_bridge.py")
            bridge_result = _run_bridge(
                [
                    str(freecadcmd),
                    "--user-cfg",
                    str(temp_dir / "freecad-user.cfg"),
                ],
                script_path=bridge_script,
                cwd=temp_dir,
                timeout=timeout,
                env=bridge_env,
            )
            if not bridge_metadata_path.is_file():
                detail = (bridge_result.stderr or bridge_result.stdout).strip()
                raise CadBuildError(
                    f"FreeCAD bridge did not report metadata: {detail}",
                    code="missing_bridge_metadata",
                    context={"returncode": bridge_result.returncode},
                )
            bridge_metadata = json.loads(bridge_metadata_path.read_text())
            if bridge_result.returncode != 0 or bridge_metadata.get("status") != "ok":
                raise CadBuildError(
                    f"FreeCAD bridge failed: {bridge_metadata.get('error', 'unknown error')}",
                    code="freecad_bridge_failed",
                    context=bridge_metadata,
                )
            if bridge_metadata.get("fallback_objects"):
                raise CadBuildError(
                    "FreeCAD used a mesh or unsupported fallback while importing OpenSCAD CSG",
                    code="non_brep_fallback",
                    context={"fallback_objects": bridge_metadata["fallback_objects"]},
                )

            try:
                imported = cq.importers.importStep(str(temporary_step))
                shapes = imported.vals()
                solids = shapes[0].Solids() if len(shapes) == 1 else []
            except Exception as exc:
                raise CadBuildError(
                    f"could not validate FreeCAD STEP output: {exc}",
                    code="invalid_step_output",
                ) from exc
            if len(solids) != 1 or not shapes[0].isValid():
                raise CadBuildError(
                    f"FreeCAD STEP must contain one valid solid, got {len(solids)}",
                    code="invalid_step_output",
                )
            export_stl(imported, temporary_stl)
            comparison = _compare_geometry(reference_stl, temporary_stl)
            failed_checks = []
            if not comparison["reference_watertight"] or not comparison["candidate_watertight"]:
                failed_checks.append("watertight")
            if comparison["reference_components"] != 1 or comparison["candidate_components"] != 1:
                failed_checks.append("components")
            if comparison["max_surface_deviation_mm"] > settings["max_surface_deviation_mm"]:
                failed_checks.append("surface_deviation")
            if comparison["relative_volume_delta"] > settings["max_relative_volume_delta"]:
                failed_checks.append("volume")
            if comparison["max_bbox_delta_mm"] > settings["max_bbox_delta_mm"]:
                failed_checks.append("bounds")
            if failed_checks:
                raise CadBuildError(
                    f"FreeCAD STEP geometry differs from OpenSCAD output: {', '.join(failed_checks)}",
                    code="geometry_mismatch",
                    context=comparison,
                )

            step_path = request.output_dir / "part.step"
            stl_path = request.output_dir / "part.stl"
            os.replace(temporary_step, step_path)
            os.replace(temporary_stl, stl_path)
            dependencies = _parse_dependencies(dependency_path, source_path.parent, source_path)
            return CadBuildResult(
                backend_name=self.name,
                step_path=step_path,
                stl_path=stl_path,
                dependencies=dependencies,
                tool_versions=self.tool_versions(request),
                settings=settings,
                metadata={"bridge": bridge_metadata, "geometry_comparison": comparison},
            )
