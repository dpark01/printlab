"""Fast-lane FEA tests: only printlab.fea.deck's pure-Python code (no gmsh, no
ccx). Deck generation, the 7-field -> 9-constant derivation, and .frd parsing
against a committed real-ccx fixture."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from printlab.fea import deck
from printlab.schemas.fea import FEALoadCase
from printlab.schemas.profiles import MaterialProfile

FIXTURE_FRD = Path(__file__).resolve().parent.parent / "fixtures" / "fea" / "sample.frd"


def _material() -> MaterialProfile:
    return MaterialProfile(
        name="Test PLA",
        material="PLA",
        density_g_cm3=1.24,
        nozzle_temp_c=(190.0, 220.0),
        bed_temp_c=(45.0, 60.0),
        young_modulus_xy_mpa=3000.0,
        young_modulus_z_mpa=2000.0,
        poisson_ratio_xy=0.35,
        poisson_ratio_xz=0.30,
        shear_modulus_xz_mpa=800.0,
        tensile_strength_xy_mpa=50.0,
        tensile_strength_z_mpa=25.0,
    )


def _single_tet() -> tuple[np.ndarray, np.ndarray]:
    nodes = np.array(
        [
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [0.0, 10.0, 0.0],
            [0.0, 0.0, 10.0],
        ]
    )
    elements = np.array([[0, 1, 2, 3]])
    return nodes, elements


def test_in_plane_shear_modulus_hand_worked():
    # G_xy = E_xy / (2 (1 + nu_xy)) = 3000 / (2 * 1.35) = 1111.11...
    assert deck.in_plane_shear_modulus(3000.0, 0.35) == pytest.approx(1111.111111, rel=1e-6)


def test_engineering_constants_order_and_values():
    constants = deck.derive_engineering_constants(_material())
    # Order: E1,E2,E3, nu12,nu13,nu23, G12,G13,G23 (== Ex,Ey,Ez,NUxy,NUxz,NUyz,Gxy,Gxz,Gyz)
    assert constants.ex == 3000.0
    assert constants.ey == 3000.0
    assert constants.ez == 2000.0
    assert constants.nuxy == 0.35
    assert constants.nuxz == 0.30
    assert constants.nuyz == 0.30
    assert constants.gxy == pytest.approx(1111.111111, rel=1e-6)
    assert constants.gxz == 800.0
    assert constants.gyz == 800.0


def test_orientation_axes_yield_build_direction_as_local_z():
    for build_direction in [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 1.0)]:
        a, b = deck.orientation_axes(build_direction)
        a = np.array(a)
        b = np.array(b)
        d = np.array(build_direction, dtype=float)
        d = d / np.linalg.norm(d)
        # CalculiX derives local Z' = X' x Y' = a x b; it must equal build_direction.
        assert np.cross(a, b) == pytest.approx(d, abs=1e-9)
        assert np.dot(a, b) == pytest.approx(0.0, abs=1e-9)


def test_build_inp_structure_keywords_in_order():
    nodes, elements = _single_tet()
    load_case = FEALoadCase(
        load_point_mm=(0.0, 0.0, 10.0),
        load_force_n=(0.0, 0.0, -5.0),
        load_region_radius_mm=2.0,
    )
    deck_result = deck.build_inp(
        nodes, elements, load_case=load_case, material=_material(), build_direction=(0.0, 0.0, 1.0)
    )
    text = deck_result.text

    expected_order = [
        "*NODE",
        "*ELEMENT, TYPE=C3D4",
        "*MATERIAL, NAME=MAT1",
        "*ELASTIC, TYPE=ENGINEERING CONSTANTS",
        "*ORIENTATION",
        "*SOLID SECTION",
        "*NSET, NSET=NFIXED",
        "*NSET, NSET=NLOAD",
        "*STEP",
        "*STATIC",
        "*BOUNDARY",
        "*CLOAD",
        "*NODE FILE",
        "*EL FILE",
        "*END STEP",
    ]
    positions = [text.find(keyword) for keyword in expected_order]
    assert all(p >= 0 for p in positions), dict(zip(expected_order, positions, strict=True))
    assert positions == sorted(positions), "deck keywords are out of order"

    # *SOLID SECTION must reference the orientation, or the anisotropy is silently
    # applied in the global frame.
    assert "ORIENTATION=ORI1" in text


def test_build_inp_engineering_constants_line():
    nodes, elements = _single_tet()
    load_case = FEALoadCase(load_point_mm=(0.0, 0.0, 10.0), load_force_n=(0.0, 0.0, -5.0))
    text = deck.build_inp(
        nodes, elements, load_case=load_case, material=_material()
    ).text
    lines = text.splitlines()
    idx = lines.index("*ELASTIC, TYPE=ENGINEERING CONSTANTS")
    first = [v.strip() for v in lines[idx + 1].split(",")]
    second = [v.strip() for v in lines[idx + 2].split(",")]
    assert first == ["3000", "3000", "2000", "0.35", "0.3", "0.3", "1111.11111", "800"]
    assert second == ["800"]


def test_build_inp_boundary_and_cload():
    nodes, elements = _single_tet()
    load_case = FEALoadCase(
        load_point_mm=(0.0, 0.0, 10.0),
        load_force_n=(0.0, 0.0, -5.0),
        load_region_radius_mm=2.0,
    )
    deck_result = deck.build_inp(
        nodes, elements, load_case=load_case, material=_material(), build_direction=(0.0, 0.0, 1.0)
    )
    # Bed contact at min z (z=0) fixes nodes 1,2,3; the tip node (z=10) is id 4.
    assert deck_result.fixed_node_ids == [1, 2, 3]
    assert deck_result.load_node_ids == [4]
    assert deck_result.warnings == []

    lines = deck_result.text.splitlines()
    assert "NFIXED, 1, 3" in lines  # constrain dofs 1..3 on the fixed set
    # Full -5 N on the single load node's dof 3 (z).
    assert "4, 3, -5" in lines


def test_build_inp_load_falls_back_to_nearest_node_with_warning():
    nodes, elements = _single_tet()
    load_case = FEALoadCase(
        load_point_mm=(100.0, 100.0, 100.0),  # far from every node
        load_force_n=(0.0, 0.0, -5.0),
        load_region_radius_mm=1.0,
    )
    deck_result = deck.build_inp(nodes, elements, load_case=load_case, material=_material())
    assert len(deck_result.load_node_ids) == 1
    assert deck_result.warnings and "nearest node" in deck_result.warnings[0]


def test_parse_frd_against_real_fixture():
    # Expected values were read once from this real ccx-2.23 output (a small
    # box cantilever); see tests/fixtures/fea/sample.frd.
    result = deck.parse_frd(FIXTURE_FRD.read_text())
    assert result.node_count == 110
    assert result.max_displacement_mm == pytest.approx(0.178690, rel=1e-4)
    assert result.max_von_mises_stress_mpa == pytest.approx(4.691992, rel=1e-4)
