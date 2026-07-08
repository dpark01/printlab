"""Pure-Python CalculiX deck writing (.inp) and result parsing (.frd).

Deliberately free of gmsh/ccx imports (only numpy, already a dependency) so
the deck-generation and result-parsing logic stays fully unit-testable with no
native tools installed -- the parts that actually need gmsh/ccx live in
printlab.fea.mesh / printlab.fea.solve.

Anisotropy is expressed with CalculiX's *ELASTIC, TYPE=ENGINEERING CONSTANTS
plus an *ORIENTATION card. Under transverse isotropy the material's local 3
axis (Ez, the weak interlayer direction) is aligned with the analysis
`build_direction`; local 1/2 span the strong in-plane layer. See
derive_engineering_constants / orientation_axes for how the 7 stored material
fields become CalculiX's 9 engineering constants + local frame.

.frd parsing is fixed-column, not whitespace-split: CalculiX writes result
values in 12-char fields that run together when a value is negative (e.g.
"-1.2E-03-3.4E-03"), so naive splitting silently drops columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

from printlab.schemas.fea import FEALoadCase
from printlab.schemas.profiles import MaterialProfile

#: A node counts as "resting on the bed" if its projection onto the build axis
#: is within this distance (mm) of the minimum -- same tolerance and rationale
#: as printlab.mesh.overhangs' bed-contact test, applied to nodes not faces.
BED_CONTACT_TOLERANCE_MM = 1e-4


class EngineeringConstants(NamedTuple):
    """The 9 values CalculiX's *ELASTIC, TYPE=ENGINEERING CONSTANTS expects, in
    order: E1,E2,E3, nu12,nu13,nu23, G12,G13,G23 (axes 1,2,3 == orientation
    local X',Y',Z')."""

    ex: float
    ey: float
    ez: float
    nuxy: float
    nuxz: float
    nuyz: float
    gxy: float
    gxz: float
    gyz: float


def in_plane_shear_modulus(young_modulus_xy_mpa: float, poisson_ratio_xy: float) -> float:
    """G_xy from the isotropic relation, valid because in-plane behavior is
    isotropic under transverse isotropy: G = E / (2 (1 + nu))."""
    return young_modulus_xy_mpa / (2.0 * (1.0 + poisson_ratio_xy))


def derive_engineering_constants(material: MaterialProfile) -> EngineeringConstants:
    """Expand the 7 stored transversely-isotropic fields into CalculiX's 9
    engineering constants. In-plane (xy) is isotropic; z is the weak axis."""
    ex = ey = material.young_modulus_xy_mpa
    ez = material.young_modulus_z_mpa
    nuxy = material.poisson_ratio_xy
    nuxz = nuyz = material.poisson_ratio_xz
    gxy = in_plane_shear_modulus(material.young_modulus_xy_mpa, material.poisson_ratio_xy)
    gxz = gyz = material.shear_modulus_xz_mpa
    return EngineeringConstants(ex, ey, ez, nuxy, nuxz, nuyz, gxy, gxz, gyz)


def orientation_axes(
    build_direction: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Two vectors (a, b) for CalculiX's rectangular *ORIENTATION such that the
    resulting local 3 axis equals `build_direction`.

    CalculiX's rectangular system: point `a` lies on local X', point `b` in the
    X'-Y' plane, and local Z' = X' x Y'. We pick a,b as an orthonormal pair
    perpendicular to the build direction with a x b == build_direction, so
    local Z' (== material axis 3, Ez) aligns with the interlayer direction. The
    specific in-plane split is arbitrary (in-plane is isotropic).
    """
    d = np.asarray(build_direction, dtype=float)
    d = d / np.linalg.norm(d)
    # Any helper not parallel to d; swap when d is ~parallel to +X.
    helper = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    a = np.cross(helper, d)
    a = a / np.linalg.norm(a)
    b = np.cross(d, a)  # b = d x a  =>  a x b == d
    b = b / np.linalg.norm(b)
    return (tuple(float(v) for v in a), tuple(float(v) for v in b))


def select_bed_contact_nodes(
    nodes: np.ndarray,
    build_direction: tuple[float, float, float],
    tolerance_mm: float = BED_CONTACT_TOLERANCE_MM,
) -> np.ndarray:
    """0-indexed node indices resting on the print bed: those whose projection
    onto the (normalized) build axis is within `tolerance_mm` of the minimum.
    Mirrors printlab.mesh.overhangs' vertex-projection bed test, on nodes."""
    d = np.asarray(build_direction, dtype=float)
    d = d / np.linalg.norm(d)
    projections = np.asarray(nodes, dtype=float) @ d
    bed_level = projections.min()
    return np.nonzero(np.abs(projections - bed_level) <= tolerance_mm)[0]


def select_box_nodes(
    nodes: np.ndarray,
    box: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> np.ndarray:
    """0-indexed node indices inside an axis-aligned (min, max) box, inclusive."""
    lo = np.asarray(box[0], dtype=float)
    hi = np.asarray(box[1], dtype=float)
    pts = np.asarray(nodes, dtype=float)
    inside = np.all((pts >= lo) & (pts <= hi), axis=1)
    return np.nonzero(inside)[0]


def select_load_nodes(
    nodes: np.ndarray,
    load_point_mm: tuple[float, float, float],
    load_region_radius_mm: float,
) -> tuple[np.ndarray, str | None]:
    """0-indexed node indices within `load_region_radius_mm` of the load point.

    Returns (indices, warning). If no node is in range, falls back to the
    single nearest node and returns a warning string; otherwise warning is
    None. Distributing the force over a small region (rather than one node)
    avoids an artificial stress singularity at the loaded point.
    """
    pts = np.asarray(nodes, dtype=float)
    point = np.asarray(load_point_mm, dtype=float)
    distances = np.linalg.norm(pts - point, axis=1)
    within = np.nonzero(distances <= load_region_radius_mm)[0]
    if within.size > 0:
        return within, None
    nearest = int(np.argmin(distances))
    warning = (
        f"no mesh node within {load_region_radius_mm} mm of load point "
        f"{tuple(load_point_mm)}; applying full load to nearest node "
        f"(index {nearest}, {distances[nearest]:.3f} mm away)"
    )
    return np.array([nearest]), warning


def _num(value: float) -> str:
    v = float(value)
    v = 0.0 if v == 0.0 else v  # normalize -0.0 so decks are stable/tidy
    return f"{v:.9g}"


def _chunk_ids(ids: list[int], per_line: int = 12) -> list[str]:
    return [", ".join(str(i) for i in ids[k : k + per_line]) for k in range(0, len(ids), per_line)]


@dataclass
class InpDeck:
    text: str
    node_count: int
    element_count: int
    fixed_node_ids: list[int]
    load_node_ids: list[int]
    warnings: list[str] = field(default_factory=list)


def build_inp(
    nodes: np.ndarray,
    elements: np.ndarray,
    *,
    load_case: FEALoadCase,
    material: MaterialProfile,
    build_direction: tuple[float, float, float] = (0.0, 0.0, 1.0),
) -> InpDeck:
    """Write a linear-static CalculiX .inp deck as text.

    `nodes` is (N,3) mm coordinates; `elements` is (M,4) linear-tet
    connectivity, 0-indexed into `nodes` (CalculiX ids are emitted 1-indexed).
    Fixed nodes come from `load_case.fixed_region` ("bed_contact" -> nodes on
    the bed for `build_direction`, else an explicit (min,max) box). The load is
    distributed evenly over the nodes near `load_case.load_point_mm`.
    """
    nodes = np.asarray(nodes, dtype=float)
    elements = np.asarray(elements, dtype=int)
    warnings: list[str] = []

    if load_case.fixed_region == "bed_contact":
        fixed_idx = select_bed_contact_nodes(nodes, build_direction)
    else:
        fixed_idx = select_box_nodes(nodes, load_case.fixed_region)
    if fixed_idx.size == 0:
        warnings.append("no nodes matched the fixed region; the model will be unconstrained")

    load_idx, load_warning = select_load_nodes(
        nodes, load_case.load_point_mm, load_case.load_region_radius_mm
    )
    if load_warning:
        warnings.append(load_warning)

    fixed_ids = sorted(int(i) + 1 for i in fixed_idx)
    load_ids = sorted(int(i) + 1 for i in load_idx)

    constants = derive_engineering_constants(material)
    axis_a, axis_b = orientation_axes(build_direction)

    lines: list[str] = []
    lines.append("*NODE, NSET=NALL")
    for i, (x, y, z) in enumerate(nodes, start=1):
        lines.append(f"{i}, {_num(x)}, {_num(y)}, {_num(z)}")

    lines.append("*ELEMENT, TYPE=C3D4, ELSET=EALL")
    for i, conn in enumerate(elements, start=1):
        n1, n2, n3, n4 = (int(c) + 1 for c in conn)
        lines.append(f"{i}, {n1}, {n2}, {n3}, {n4}")

    lines.append("*MATERIAL, NAME=MAT1")
    lines.append("*ELASTIC, TYPE=ENGINEERING CONSTANTS")
    # 8 constants on line 1, the 9th (G23) on line 2 -- CalculiX's fixed
    # 8-values-per-line convention for this card.
    lines.append(
        ", ".join(
            _num(v)
            for v in (
                constants.ex,
                constants.ey,
                constants.ez,
                constants.nuxy,
                constants.nuxz,
                constants.nuyz,
                constants.gxy,
                constants.gxz,
            )
        )
    )
    lines.append(_num(constants.gyz))

    # *ORIENTATION must be defined before the *SOLID SECTION that references it,
    # and the section must name it, or the engineering constants would be
    # interpreted in the global frame (silently wrong for an anisotropic part).
    lines.append("*ORIENTATION, NAME=ORI1, SYSTEM=RECTANGULAR")
    lines.append(", ".join(_num(v) for v in (*axis_a, *axis_b)))
    lines.append("*SOLID SECTION, ELSET=EALL, MATERIAL=MAT1, ORIENTATION=ORI1")

    lines.append("*NSET, NSET=NFIXED")
    lines.extend(_chunk_ids(fixed_ids))
    lines.append("*NSET, NSET=NLOAD")
    lines.extend(_chunk_ids(load_ids))

    lines.append("*STEP")
    lines.append("*STATIC")
    lines.append("*BOUNDARY")
    lines.append("NFIXED, 1, 3")

    n_load = len(load_ids)
    force_per_node = tuple(component / n_load for component in load_case.load_force_n)
    lines.append("*CLOAD")
    for node_id in load_ids:
        for dof, component in enumerate(force_per_node, start=1):
            if component != 0.0:
                lines.append(f"{node_id}, {dof}, {_num(component)}")

    lines.append("*NODE FILE")
    lines.append("U")
    lines.append("*EL FILE")
    lines.append("S")
    lines.append("*END STEP")

    text = "\n".join(lines) + "\n"
    return InpDeck(
        text=text,
        node_count=len(nodes),
        element_count=len(elements),
        fixed_node_ids=fixed_ids,
        load_node_ids=load_ids,
        warnings=warnings,
    )


class FrdResult(NamedTuple):
    max_displacement_mm: float
    max_von_mises_stress_mpa: float
    node_count: int


# CalculiX .frd nodal result records are fixed-width: cols 0:3 = record flag
# (" -1"), 3:13 = node id (I10), then 12-char value fields.
_FRD_NODE_SLICE = slice(3, 13)
_FRD_VALUE_WIDTH = 12
_FRD_VALUES_START = 13


def _frd_values(line: str, count: int) -> list[float]:
    values: list[float] = []
    for k in range(count):
        start = _FRD_VALUES_START + k * _FRD_VALUE_WIDTH
        values.append(float(line[start : start + _FRD_VALUE_WIDTH]))
    return values


def _von_mises(sxx: float, syy: float, szz: float, sxy: float, syz: float, szx: float) -> float:
    return float(
        np.sqrt(
            0.5
            * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
            + 3.0 * (sxy**2 + syz**2 + szx**2)
        )
    )


def parse_frd(text: str) -> FrdResult:
    """Extract peak nodal displacement magnitude and peak von Mises stress from
    a CalculiX .frd file.

    Reads the DISP block (components D1,D2,D3 -> magnitude) and the STRESS block
    (SXX,SYY,SZZ,SXY,SYZ,SZX -> von Mises). CalculiX does not write von Mises
    directly for an *EL FILE S request, so it is computed from the 6 tensor
    components. Blocks open on a " -4  <NAME>" line and data rows begin " -1".
    """
    max_disp = 0.0
    max_vm = 0.0
    disp_nodes = 0

    block: str | None = None
    for line in text.splitlines():
        flag = line[:3]
        if flag == " -4":
            name = line[3:].split()[0] if line[3:].split() else ""
            block = name
            continue
        if flag == " -3":
            block = None
            continue
        if flag != " -1":
            continue
        if block == "DISP":
            ux, uy, uz = _frd_values(line, 3)
            magnitude = (ux * ux + uy * uy + uz * uz) ** 0.5
            max_disp = max(max_disp, magnitude)
            disp_nodes += 1
        elif block == "STRESS":
            sxx, syy, szz, sxy, syz, szx = _frd_values(line, 6)
            max_vm = max(max_vm, _von_mises(sxx, syy, szz, sxy, syz, szx))

    return FrdResult(max_displacement_mm=max_disp, max_von_mises_stress_mpa=max_vm, node_count=disp_nodes)
