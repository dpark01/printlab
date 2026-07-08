"""Heavy-lane FEA acceptance test: mesh + solve examples/hook end to end and
check the result against Euler-Bernoulli beam theory.

Self-skips exactly like the slicer-dependent integration tests: `gmsh` must be
importable (the `fea` extra) and a CalculiX binary must be found. Uses
skip_unless_importable() rather than pytest.importorskip() directly because
gmsh's C extension dlopen()s libGLU at import time, which raises OSError (not
ImportError) when that shared library is missing -- see tests.conftest. We
use printlab.fea.solve.find_ccx_binary() rather than shutil.which("ccx")
because the binary is commonly installed version-suffixed (e.g. `ccx_2.23`).
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from tests.conftest import skip_unless_importable

skip_unless_importable("gmsh")

from printlab import pipeline  # noqa: E402
from printlab.fea import analyze, solve  # noqa: E402
from printlab.profiles import load_material_profile  # noqa: E402
from printlab.schemas.common import Status  # noqa: E402
from printlab.schemas.fea import FEALoadCase  # noqa: E402

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


def _skip_if_no_ccx() -> None:
    if solve.find_ccx_binary() is None:
        pytest.skip("CalculiX 'ccx' binary not installed on this machine")


def _hook_constants():
    spec = importlib.util.spec_from_file_location("hook_part", EXAMPLES_DIR / "hook" / "part.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def hook_step(tmp_path_factory) -> Path:
    config = pipeline.load_part_config(EXAMPLES_DIR / "hook", repo_root=REPO_ROOT)
    out = tmp_path_factory.mktemp("hook_fea")
    step_path, _ = pipeline.stage_build(config, out)
    return step_path


@pytest.fixture(scope="module")
def material():
    return load_material_profile(REPO_ROOT / "profiles/materials/pla.yaml")


def _euler_bernoulli_arm_deflection_mm(material) -> float:
    # Cantilever tip deflection delta = F L^3 / (3 E I) for the hook's arm.
    # The arm axis lies in the strong in-plane (xy) layer -- it is perpendicular
    # to the default build direction (+Z, the weak interlayer axis) -- so the
    # bending modulus is young_modulus_xy_mpa. I = pi r^4 / 4 (solid circle).
    hook = _hook_constants()
    force_n = 10.0
    length_mm = hook.ARM_LENGTH
    modulus_mpa = material.young_modulus_xy_mpa
    second_moment = math.pi * hook.ARM_RADIUS**4 / 4.0
    return force_n * length_mm**3 / (3.0 * modulus_mpa * second_moment)


def test_hook_arm_matches_beam_theory_when_plate_is_fixed(hook_step, material):
    """Isolate the arm cantilever (fix the whole mounting plate) so beam theory
    actually applies, and check FEA lands close to Euler-Bernoulli.

    Observed ~1.1x EB: FEA is slightly softer (shear deformation in a stubby
    L/r~5 beam plus the upturned tip's added compliance), which the crude linear
    C3D4 mesh only partly stiffens back. The band is generous on purpose -- this
    is a sanity check, not a converged model."""
    _skip_if_no_ccx()
    hook = _hook_constants()
    tip = (0.0, hook.PLATE_THICKNESS + hook.ARM_LENGTH, hook.ARM_Z)
    plate_box = ((-16.0, -1.0, -1.0), (16.0, hook.PLATE_THICKNESS + 0.01, 45.0))
    load_case = FEALoadCase(
        fixed_region=plate_box,
        load_point_mm=tip,
        load_force_n=(0.0, 0.0, -10.0),
        load_region_radius_mm=4.0,
    )
    report = analyze(hook_step, load_case, material, build_direction=(0.0, 0.0, 1.0))

    expected = _euler_bernoulli_arm_deflection_mm(material)
    assert report.mesh_element_count > 0
    assert report.solver == "calculix"
    assert 0.5 * expected <= report.max_displacement_mm <= 2.5 * expected, (
        f"FEA {report.max_displacement_mm:.5f} mm vs Euler-Bernoulli {expected:.5f} mm"
    )


def test_hook_bed_contact_end_to_end(hook_step, material):
    """The documented default path: fix the bed-contact nodes and load the arm
    tip. Max displacement is the WHOLE-part max (the upturned tip top swings
    most) and is far larger than the arm-only beam value because the thin
    mounting plate -- fixed only along its bottom edge -- dominates compliance.
    So we bound it below by the arm-only deflection and above by a generous cap,
    and check the artifact is coherent rather than pinning an exact number."""
    _skip_if_no_ccx()
    hook = _hook_constants()
    tip = (0.0, hook.PLATE_THICKNESS + hook.ARM_LENGTH, hook.ARM_Z)
    load_case = FEALoadCase(
        load_point_mm=tip,
        load_force_n=(0.0, 0.0, -10.0),
        load_region_radius_mm=4.0,
    )
    report = analyze(hook_step, load_case, material)

    arm_only = _euler_bernoulli_arm_deflection_mm(material)
    assert report.status == Status.OK
    assert report.build_direction == (0.0, 0.0, 1.0)
    assert report.mesh_node_count > 0 and report.mesh_element_count > 0
    assert report.max_von_mises_stress_mpa > 0.0
    assert report.safety_factor is not None and report.safety_factor > 1.0
    # Plate compliance makes the real structure softer than the arm alone, but
    # not absurdly so for a 10 N load on a chunky PLA hook.
    assert arm_only < report.max_displacement_mm < 3.0
