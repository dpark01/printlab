# FEA (v1): linear-static analysis via CalculiX

`printlab fea <example_dir>` runs a crude, single-run linear-static finite
element analysis: fix the part where it rests on the print bed, apply one
point load, and report peak displacement and peak von Mises stress. It is a
triage tool, not a certification-grade simulation — see "What this is not"
below.

## Why CalculiX

Evaluated CalculiX, Elmer FEM, and FreeCAD's FEM workbench. CalculiX won:

- Free, GPL, actively maintained (pinned at 2.23 in `tools.toml`).
- A pure CLI solver (`ccx jobname` reads `jobname.inp`, writes
  `jobname.frd`/`.dat`) — no GUI, no interactive state, maps directly onto
  the same `tools.toml`/`printlab doctor`/graceful-skip pattern the three
  slicers already use.
- Unlike the slicers, it's a small, GUI-free package installable via
  `apt-get install calculix-ccx` on Debian/Ubuntu — genuinely CI-friendly.
- FreeCAD's FEM workbench turned out to just be a GUI wrapper *around*
  CalculiX or Elmer anyway, adding a large, more brittle dependency for no
  unique capability. Elmer needs more scaffolding (a separate mesh-conversion
  tool, a more verbose multi-block config) for a case this simple.

## Why STEP, not STL

FEA needs a volumetric (tetrahedral) mesh; an STL is an unparametrized
"triangle soup" that needs error-prone reparametrization before it can be
tetrahedralized cleanly. PrintLab already exports STEP from CadQuery
(`stage_build` → `export_step`), and Gmsh's OCC kernel meshes a STEP file
directly (`gmsh.model.occ.importShapes`) — reusing an artifact PrintLab
already produces instead of adding a new CAD export.

## The pipeline

```
part.step -> Gmsh (linear tets)         printlab/fea/mesh.py         (needs the `fea` extra)
             via an isolated subprocess printlab/fea/mesh_runner.py  (spawns _mesh_worker.py)
          -> CalculiX .inp deck         printlab/fea/deck.py         (pure Python)
          -> ccx solve                  printlab/fea/solve.py       (needs `ccx` on PATH)
          -> .frd parse -> FEAReport    printlab/fea/deck.py
```

Split so the parts that don't need native tools stay unit-testable:
`deck.py` (deck writing + `.frd` parsing) is pure Python and tested against a
real captured `ccx` output fixture (`tests/fixtures/fea/sample.frd`); only
`mesh.py` needs `gmsh` and only `solve.py` needs `ccx`. `mesh_runner.py`
itself needs neither -- it only shells out to `python -m
printlab.fea._mesh_worker`, mirroring `solve.py`'s `run_ccx()` subprocess
convention (list-form args, no shell, explicit timeout).

**Meshing runs in a subprocess, not in-process.** `printlab.fea.analyze()`
used to call `mesh.py`'s `mesh_step()` directly. Gmsh's Python API installs a
SIGINT handler on `gmsh.initialize()` by default, which only works on the
main thread -- but FastMCP dispatches `printlab_fea` off-thread, so `mesh.py`
already had to pass `interruptible=False` to avoid an immediate crash on
that call alone. That workaround didn't cover the actual failure mode: on a
part combining a large overall footprint with fine local features (e.g. a
0.35mm hinge gap next to a 78mm box), the default characteristic mesh size
(~1/20 of the bounding-box diagonal) is far coarser than the fine feature,
Gmsh raises `Invalid boundary mesh (overlapping facets)`, and that failure --
happening on the FastMCP worker thread -- was observed to kill the whole MCP
server process, with every subsequent tool call failing until the client
reconnected. `mesh_runner.run_mesh_worker()` now runs the actual meshing in a
child process (`python -m printlab.fea._mesh_worker`); a Gmsh-level failure
there, on whatever thread it occurs, can only kill that child and surfaces
to the caller as an ordinary `RuntimeError` with the failure's stderr tail.
This subprocess boundary produces numerically identical results to the old
in-process call (same Gmsh version, same inputs) -- see
`tests/integration/test_fea_hook.py`, unchanged by this refactor.

**`mesh_size_mm` overrides the default sizing.** `FEALoadCase.mesh_size_mm`
(optional, `printlab.toml`'s `[fea]` table) is threaded straight through to
`mesh_step()`, for exactly the large-footprint/fine-feature case above where
the default heuristic is too coarse. Left unset, the ~diagonal/20 default is
unchanged. `printlab_fea_preview` (`printlab fea-preview` on the CLI) is a
cheap, `ccx`-free way to try a candidate `mesh_size_mm` before a real
`printlab_fea` run: it meshes (in the same isolated subprocess) and reports
node/element counts, or a structured `status="error"` on failure -- never a
crash -- so tuning `mesh_size_mm` for an unfamiliar part doesn't require
risking a full FEA round trip.

**Linux system dependency, easy to miss:** `pip install`/`uv sync --extra
fea` alone is not enough on Linux. `gmsh`'s compiled extension `dlopen()`s
`libGLU` at import time -- even though PrintLab only calls its headless
meshing API, never its GUI/OpenGL viewer -- so a system missing that shared
library fails with `OSError: libGLU.so.1: cannot open shared object file`,
not an install error. On Debian/Ubuntu: `apt-get install libglu1-mesa`
(pulled in automatically on most desktop Linux installs, but not on a bare
CI runner or minimal container -- this bit CI directly before it was added
to `.github/workflows/ci.yml`). Tests guard against this with
`tests.conftest.skip_unless_importable()` rather than plain
`pytest.importorskip()`, since the latter only catches `ImportError`.

## Load case

FEA needs to know where a part is held and where a load is applied. This is
declarative config in `printlab.toml`, not CAD source — consistent with
PrintLab's "engineering constraints live in profiles/config, not `part.py`"
principle:

```toml
[fea]
load_point_mm = [0.0, 34.0, 28.0]   # a point in the part's STEP/STL frame
load_force_n = [0.0, 0.0, -10.0]    # applied force vector, newtons
load_region_radius_mm = 4.0         # distribute the load over nodes within this radius (optional, default 2.0)
# fixed_region omitted -> "bed_contact" default (see below)
# mesh_size_mm omitted -> ~1/20 of the bounding-box diagonal (optional override; see "The pipeline" above)
```

`fixed_region` defaults to `"bed_contact"`: every mesh node resting on the
print bed (the same "minimum projection onto the build direction" concept
`printlab.mesh.overhangs` already uses to decide which faces don't count as
overhangs) is fully constrained — a printed part is physically held there by
bed adhesion. Pass an explicit box instead
(`fixed_region = [[xmin,ymin,zmin],[xmax,ymax,zmax]]`) to fix a different
region (e.g. simulating a bolted mount instead of a bed-glued base).

The load is a single force vector distributed evenly across every mesh node
within `load_region_radius_mm` of `load_point_mm` (falling back to the
single nearest node if none are in range) — spreading it avoids a stress
singularity at one node. Only `examples/hook` has an `[fea]` section today,
with the load point at the hook arm's free end and a 10 N downward pull, as
if something were hung on it.

## Material properties are orthotropic — and placeholders

FDM/FFF parts are stiffer and stronger in-plane, within a layer ("xy"), than
through the layer stack ("z", the build direction) — interlayer bonds are
weaker than continuous extruded roads. `MaterialProfile`
(`printlab/schemas/profiles.py`) models this as **transverse isotropy** (7
fields: in-plane and through-thickness Young's modulus, two Poisson ratios, an
out-of-plane shear modulus, and two tensile strengths), oriented per-analysis
via CalculiX's `*ORIENTATION` card against whatever `build_direction` the
analysis uses — not fixed world axes.

**These are literature placeholder values, not measured or calibrated for
any specific printer+filament+process** — exactly as provisional as
`PrintabilityReport.provisional_score` (see `printlab/schemas/evaluation.py`;
the same "explicitly flagged, uncalibrated" stance applies here). Treat
`fea_report.json`'s numbers as order-of-magnitude, not certification-grade,
until real coupon-test data replaces them. `profiles/materials/pla.yaml` is
the only material profile today and comments each placeholder's basis.

## Acceptance check: hook vs. Euler-Bernoulli

`tests/integration/test_fea_hook.py` cross-checks the hook's cantilevered
arm, isolated with its own base fixed, against the classic beam formula
`δ = F·L³ / (3·E·I)`. FEA landed within ~10% of hand calculation — strong
agreement for a crude single-run linear-tet mesh. The full-part default
(`fixed_region = "bed_contact"`) reports a much larger displacement, and
that's real physics, not a bug: the mounting plate is only ~4mm thick and
fixed along one edge, so it dominates whole-part compliance far more than
the arm itself does — `max_displacement_mm` is a whole-part maximum, not an
arm-only figure.

## What this is not

- **Not certification-grade.** A crude single-run linear-static analysis on
  a coarse, deterministically-generated (but not convergence-verified) tet
  mesh, with placeholder material constants. No mesh refinement study, no
  nonlinear/large-deflection modeling.
- **Not deterministic mesh-for-mesh across runs.** Gmsh's tetrahedralization
  can produce a slightly different node/element count between separate
  invocations (observed directly: 855 vs. 908 nodes for the same hook STEP
  file, seconds apart) — this can shift exactly which nodes fall within
  `load_region_radius_mm` of the load point, occasionally triggering the
  nearest-node fallback (and its warning) instead of the multi-node
  distribution. `max_displacement_mm`/`max_von_mises_stress_mpa` still land
  in the same order of magnitude across such runs, but treat them as
  reproducible-enough-for-triage, not the same Tier-1 hash-identical
  contract the rest of PrintLab's artifacts hold to.
- **Not anisotropy-calibrated.** The material model shape (transverse
  isotropy) is real; the numbers plugged into it are not.
- **Not part of `printlab all`'s critical path.** Explicit only, like
  `orient`/`repair`/`render`.
