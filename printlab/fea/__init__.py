"""Finite-element analysis (v1): STEP part -> linear-static FEAReport.

Orchestration only -- the real work lives in the sibling modules, split so the
pure-Python deck/parse logic (deck.py) stays testable without the native
solver, and the gmsh/ccx-dependent pieces (mesh.py, solve.py) are isolated:

    mesh.py        STEP -> linear-tet nodes/elements (Gmsh), in-process
    mesh_runner.py runs mesh.py's mesh_step() in an isolated subprocess (see
                   its docstring for why: a Gmsh-level failure must not be
                   able to kill the caller, e.g. the MCP server)
    deck.py        nodes/elements + load case + material -> CalculiX .inp / parse .frd
    solve.py       find and run ccx

The default boundary condition fixes the nodes resting on the print bed, since
a printed part is physically held there by bed adhesion. This is a crude
single-run linear analysis on PLACEHOLDER material constants -- see
printlab.schemas.fea for the honesty caveats.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from printlab.determinism import hash_file
from printlab.fea import deck as deck_mod
from printlab.fea import solve as solve_mod
from printlab.schemas.common import ArtifactError, Status
from printlab.schemas.fea import FEALoadCase, FEAReport
from printlab.schemas.profiles import MaterialProfile

__all__ = ["analyze"]


def analyze(
    step_path: Path,
    load_case: FEALoadCase,
    material: MaterialProfile,
    *,
    build_direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> FEAReport:
    """Run a linear-static FEA of `step_path` under `load_case` and return an
    FEAReport. Requires the `fea` extra (gmsh) and `ccx` on PATH; raises if the
    solver is missing or the run produces no result file.

    Meshing runs in an isolated subprocess (printlab.fea.mesh_runner) rather
    than in-process, so a Gmsh-level meshing failure can only kill that child,
    not the caller -- see mesh_runner's docstring and issue #4.
    """
    from printlab.fea import mesh_runner

    step_path = Path(step_path)
    input_sha256 = hash_file(step_path)

    nodes, elements, _resolved_mesh_size_mm = mesh_runner.run_mesh_worker(
        step_path, mesh_size_mm=load_case.mesh_size_mm
    )
    inp = deck_mod.build_inp(
        nodes,
        elements,
        load_case=load_case,
        material=material,
        build_direction=build_direction,
    )

    with tempfile.TemporaryDirectory(prefix="printlab_fea_") as scratch:
        inp_path = Path(scratch) / "job.inp"
        inp_path.write_text(inp.text)
        completed = solve_mod.run_ccx(inp_path)
        frd_path = inp_path.with_suffix(".frd")
        if completed.returncode != 0 or not frd_path.is_file():
            tail = (completed.stdout or "")[-2000:]
            raise RuntimeError(
                f"CalculiX run failed (exit {completed.returncode}); no usable .frd. "
                f"Last output:\n{tail}"
            )
        frd = deck_mod.parse_frd(frd_path.read_text())

    strength = min(material.tensile_strength_xy_mpa, material.tensile_strength_z_mpa)
    safety_factor = (
        strength / frd.max_von_mises_stress_mpa if frd.max_von_mises_stress_mpa > 0.0 else None
    )

    errors = [
        ArtifactError(code="fea_warning", message=warning, stage="fea") for warning in inp.warnings
    ]
    status = Status.WARNING if errors else Status.OK

    return FEAReport(
        status=status,
        errors=errors,
        input_path=step_path,
        input_sha256=input_sha256,
        solver_version=solve_mod.detect_ccx_version(),
        load_case=load_case,
        build_direction=build_direction,
        mesh_node_count=inp.node_count,
        mesh_element_count=inp.element_count,
        max_displacement_mm=frd.max_displacement_mm,
        max_von_mises_stress_mpa=frd.max_von_mises_stress_mpa,
        safety_factor=safety_factor,
    )
