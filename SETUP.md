# PrintLab
## A Reproducible Agentic Engineering Environment for 3D-Printable Mechanical Design

**Version:** 0.2 Draft

---

# Implementation Status (as of 2026-07-08)

This document is the original design draft and is kept as-is below for
historical reference. This section tracks what has actually been built
against it, and what remains. See `README.md` for the day-to-day quickstart
and `AGENTS.md` for the agent operating rules; specific deviations from this
draft's assumptions are documented in-line in the relevant module docstrings
(`printlab/determinism.py`, `printlab/schemas/evaluation.py`,
`printlab/gcode/parser.py`, `printlab/mesh/wall_thickness.py`,
`printlab/slicing/orcaslicer.py`) rather than repeated here.

## Done

**v0.1 vertical slice** (one part, one backend, full abstraction):
- Python package (`uv`-managed), Typer CLI, `pyproject.toml`/`uv.lock`/`.python-version`
- Printer/material/process profile system: the 3-part split (engineering
  constraints + native config bundle + small override allowlist) rather than
  a universal slicer schema
- CAD backend: CadQuery (the draft's other option; not build123d)
- Generic slicer abstraction (`SlicerBackend` / `PrusaLikeBackend`)
- Mesh analysis via trimesh: manifold, watertight, self-intersection
  heuristic, shell count, bbox, volume, surface area
- Structured JSON reports: Pydantic v2, a shared `schema_version`/`status`/
  `errors[]` envelope, committed JSON Schemas under `docs/schemas/`
- Markdown reports
- One example parametric model (`examples/bracket`)
- Unit tests requiring neither a CAD kernel nor a slicer; capability-gated
  integration tests
- GitHub Actions CI (fast lane + heavy lane + a `requirements.txt`/`uv.lock`
  sync check)
- Provenance (`run_manifest.json`: tool versions + content hashes) and a
  three-tier reproducibility contract (`printlab/determinism.py`) --
  verified empirically (two independent runs into different directories
  produce hash-identical normalized artifacts), not just asserted
- Environment reproducibility: `tools.toml` pins, `printlab doctor`,
  `scripts/setup-macos.sh` / `scripts/setup-linux.sh`
- Bambu Studio CLI adapter
- PrusaSlicer CLI adapter

**Phase A -- round out the vertical slice (all five items done):**
- A.1 second example part, `examples/hook`, with a genuine cantilevered
  overhang the bracket doesn't have
- A.2 `quality`/`strength` process profiles alongside `draft` (surfaced and
  fixed a real bug along the way: `wall_count` was documented as part of the
  override allowlist but never actually resolved or passed to a backend)
- A.3 HTML report (`printlab/reporting/html.py`)
- A.4 basic mesh repair (`printlab/mesh/repair.py`, `printlab repair` CLI
  command) -- not wired into `printlab all`'s critical path; explicitly
  invoked, since CadQuery-sourced STLs are already clean by construction
- A.5 OrcaSlicer evaluated and added as a third backend. The original
  justification ("richer CLI") did not hold up under direct testing -- its
  CLI and G-code conventions turned out nearly identical to Bambu Studio's --
  but it bundles a substantially broader vendor profile library while
  remaining Bambu-compatible, which is a real, verified reason to keep it
  (`printlab/slicing/orcaslicer.py`)

**Phase B -- manufacturing-tractability metrics (B.6-B.9, all done):**
- B.6 overhang histogram (`printlab/mesh/overhangs.py`): per-face-normal
  classification against a build direction, bucketed by angle from vertical
- B.7 minimum wall thickness estimation (`printlab/mesh/wall_thickness.py`):
  went through two real bugs (inward-vs-outward ray direction, a backward
  epsilon nudge that made every face read exactly the epsilon value) and one
  real design finding (reporting the strict minimum across faces is
  fundamentally fragile at sharp edges -- even a single plain capped
  cylinder falsely read ~4.6mm instead of its true ~12mm diameter; a low
  percentile across faces is the standard, more robust fix) -- see the
  module docstring for the full account
- B.8 unsupported span ("bridge") detection (`printlab/mesh/bridges.py`):
  connected-component grouping of overhang faces, reporting the longest
  region's projected span
- B.9 orientation search (`printlab/mesh/orientation.py`, `printlab orient`):
  pure orchestration over B.6-B.8 as originally scoped -- evaluates the 6
  axis-aligned rotations against a *copy* of the mesh and ranks by the
  documented tie-break chain (minimize `overhang_area_mm2`, then maximize
  `min_wall_thickness_mm`, then minimize `max_unsupported_span_mm`; no
  weighted scalar). Mesh-metrics-only ranking, as scoped -- candidates are
  not re-sliced. Concretely verified on the acceptance case this item was
  written against: `examples/hook`'s default-orientation cantilever
  (`max_unsupported_span_mm` ~32.3mm) drops to 20.0mm and overhang area drops
  from ~323mm² to ~105mm² when rotated 90° about X -- exactly the fix this
  item was originally proposed to demonstrate. New artifact:
  `orientation_search_report.json` (`OrientationSearchReport` in
  `printlab/schemas/orientation.py`).

**Also done, ahead of their own sections below:**
- C.11 agent optimization loop (`scripts/optimize_loop.py`) -- see its own
  entry under Phase C for what shipped and why it isn't blocked by C.10.
- A slicer-free `printlab check <example_dir>` command
  (`printlab.pipeline.run_check`) -- not part of the original draft, added
  because it turned out `printlab all` hard-fails without a slicer (`stage_slice`
  returns a `binary_not_found`-error `SliceResult`, and `run_all` propagates
  that as a `PipelineError`), which meant `printability_report.json` and the
  reports were unreachable without one even though the checks that matter
  most (manifold, build-volume fit, wall thickness) are all mesh-derived.
  `check` runs build -> mesh -> evaluate -> report with slicing skipped
  entirely; gcode-derived metrics/checks degrade to `null`/`warning` rather
  than blocking. This is also what made C.11 and B.9's acceptance tests
  runnable without installing a slicer.
- Two more example parts, `examples/thinwall` (wall thickness ~0.25mm,
  robustly below the Bambu A1's 0.4mm minimum feature size) and
  `examples/bridge` (a two-support bridge with a genuine 40mm-gap
  unsupported span, distinct in kind from the hook's cantilever) -- these
  are the "third and fourth example part" C.10 calls for below, added ahead
  of the score itself since they're useful calibration data regardless of
  when weights get picked.
- A third example, `examples/canoe`, joined all three golden/integration
  `EXAMPLE_NAMES` suites -- its persistent `warning` status (engraved-text
  wall-thickness ray-cast noise) is harmless to every assertion in those
  files, which check hash-reproducibility and slice success, not overall
  printability status.
- `printlab render` (`printlab/rendering/`, Phase D's vision-loop
  prerequisite, pulled forward -- see below): matplotlib/Agg offscreen PNG
  rendering from named presets or an arbitrary camera angle, with a
  `RenderReport` recording the deterministic camera metadata (never the PNG
  bytes, which -- like `part.stl` -- are rendering-library-version
  dependent). Needed zero new dependencies: matplotlib is already resolved
  transitively via `vtk`/`cadquery-ocp`.
- FEA v1 (`printlab/fea/`, `printlab fea`) -- see its own entry under Phase D
  below for the full account.
- An MCP server and two Claude Code skills (`printlab_mcp/`,
  `.claude/skills/`) -- see the "Adapters may be built later" note under
  Phase D below.

## Not done -- a handoff for whoever (or whichever agent) picks this up next

This section is written so a fresh agent with no memory of prior sessions can
act on it directly: concrete files to create, what to reuse, and open
questions to resolve rather than assume.

### Phase C -- scoring -- C.10 partly landed (uncalibrated), C.11 done

**C.10: a calibrated composite printability score.** The prior deferral was
reconsidered: rather than waiting indefinitely for calibration data,
`printability_report.json` now carries a `provisional_score` (0-100) and a
`score_calibrated: bool` field that is `False` in every v1 report --
deliberately machine-readable, not just a docstring warning, so a caller can
branch on "is this trustworthy" without reading anything. The formula
(`printlab/evaluation/printability.py`) is a fixed, arbitrary penalty per
failing check (`ERROR_PENALTY = 40`, `WARNING_PENALTY = 10`, floored at 0) --
deliberately not per-metric weights, since weights are exactly what would
need real calibration; a flat penalty is a more honest placeholder. What
"calibration data" concretely means is unchanged: run the pipeline across a
range of example parts and, ideally, real print outcomes (did it actually
print successfully?), then fit or justify real weights against that data --
the variety this needs ("something with a known-bad wall thickness,
something requiring real support material") already exists (`examples/
thinwall`, `examples/bridge`, alongside `bracket`/`hook`/`canoe`); what's
still missing is real print-outcome data and the fitting work itself, at
which point `score_calibrated` can flip to `True`. Until then, treat
`provisional_score` as triage-only and the individual `checks[]`/`metrics{}`
as the source of truth -- `scripts/optimize_loop.py` targets a specific
named metric, never this score, and B.9's `rank_candidates()` deliberately
does not use it either (see `printlab/mesh/orientation.py`: a coarse
whole-part triage integer would discard the resolution its tie-break chain
needs, and orientation candidates don't even run the full check suite).

**C.11: an agent optimization loop -- done (`scripts/optimize_loop.py`).**
Lives *outside* the engineering modules, as this draft's own design rule
required -- a standalone script, not inside `printlab/pipeline.py`, and it
is not itself a source of engineering truth (it only reads
`printability_report.json`'s existing metrics/checks). Implements exactly
the three pieces called for: (a) `propose_edit(source, last_result) -> str |
None` is a pluggable callback -- PrintLab itself never calls an LLM,
matching the LLM-agnostic core philosophy -- with a deterministic demo
proposer (`make_constant_nudge_proposer`) shipped so the loop runs and tests
with zero LLM; (b) it re-runs a pluggable `runner` (defaults to the new
`printlab.pipeline.run_check`, so the demo needs no slicer; also works with
`run_all`) after each edit; (c) the stopping rule was implemented as
suggested, without needing C.10: stop once no ERROR-level check remains and
the target metric hasn't improved for `patience` consecutive iterations, or
the proposer returns `None`, or `max_iters` is reached. One refinement found
during testing: an iteration whose printability status is `error` must never
be recorded as the "best" result even if its raw metric value looks better
numerically -- a broken design isn't a valid candidate to compare against.
The example's CAD source is restored to its original content when the loop
returns, regardless of outcome.

### Phase D -- vision loop prerequisite and FEA v1 done; full vision loop still open

**`render` -- done, pulled forward as this draft's own note anticipated.**
The refinement recorded here previously has held up in practice: a
vision-*capable* coding agent already has the "vision model" built into
itself (it can view an image via its own tool use), so what Phase D actually
needed from PrintLab was just a cheap `render` capability, not a bespoke
vision-model API integration. `printlab render <example_dir>` (`printlab/
rendering/`) renders `part.stl` to PNGs via matplotlib's Agg backend --
already a transitive dependency (via `vtk`/`cadquery-ocp`), so this needed
zero new installs, and Agg's pure-offscreen rasterization sidesteps the
headless-GL problem that rules out `trimesh.Scene.save_image()` (needs
`pyglet` and a GL context, neither available here) -- from either named
presets (`iso`/`front`/`back`/`left`/`right`/`top`/`bottom`) or an arbitrary
`--elevation`/`--azimuth`. A `render_report.json` records the deterministic
camera metadata; the PNG bytes themselves are deliberately never hashed
(matplotlib-version-dependent, the same reasoning that already excludes
`part.stl`'s bytes). The full vision *loop* (agent looks, proposes,
validates, iterates) is now literally just an agent calling `printlab
render` alongside the existing JSON artifacts -- no further PrintLab
infrastructure needed; that loop itself remains unscoped/undemonstrated as
a concrete workflow.

**FEA v1 -- done (`printlab/fea/`, `printlab fea`), scoped to a single
linear-static case.** Evaluated CalculiX, Elmer FEM, and FreeCAD's FEM
workbench; chose **CalculiX**: a free, actively-maintained, pure-CLI solver
that maps directly onto the existing `tools.toml`/`printlab doctor`/
graceful-skip pattern the three slicers already use, and -- unlike them --
is a small enough headless package to actually install in CI
(`apt-get install calculix-ccx`). FreeCAD's FEM workbench turned out to be a
GUI wrapper *around* CalculiX/Elmer anyway (no unique capability, much
heavier dependency); Elmer needed more scaffolding for no benefit here.

Meshes from **STEP, not STL** -- a real, verified architectural choice: an
STL is unparametrized "triangle soup" that resists clean tetrahedralization,
while PrintLab already exports STEP (`stage_build` -> `export_step`), which
Gmsh's OCC kernel meshes directly. Split into `printlab/fea/{mesh,deck,
solve}.py` so the parts needing no native tool (deck writing, `.frd`
parsing) stay unit-testable without `gmsh`/`ccx` installed. `MaterialProfile`
gained 7 transversely-isotropic elastic/strength fields (in-plane vs.
through-layer, oriented per-analysis via CalculiX's `*ORIENTATION` card
against the analysis's build direction) -- explicitly literature
placeholders, not measured, exactly as uncalibrated as C.10's
`provisional_score` above (see `docs/fea.md`). The load case (fixed region +
one point load) is declarative config in `printlab.toml`'s `[fea]` table,
not CAD source; the default fixed region reuses `printlab.mesh.overhangs`'s
existing bed-contact concept rather than inventing a new one, since a
printed part really is held by bed adhesion at its base.

Acceptance check: `examples/hook`'s cantilevered arm, isolated with its own
base fixed, landed within ~10% of a hand-calculated Euler-Bernoulli beam
deflection -- strong agreement for a crude single-run linear-tet mesh on
placeholder constants. One real limitation surfaced and documented (not
fixed, since it needs a harder mesh-determinism investigation out of scope
for v1): Gmsh's tetrahedralization is not perfectly reproducible run-to-run
(observed directly: 855 vs. 908 nodes for the same input, seconds apart),
so `fea_report.json` does not carry the same Tier-1 hash-identical
reproducibility guarantee the rest of PrintLab's artifacts do -- see
`docs/fea.md`'s "What this is not" section. One integration bug found and
fixed along the way: `gmsh.initialize()` installs a SIGINT handler by
default, which Python only permits from the main thread of the main
interpreter -- this silently broke `printlab_fea` specifically when called
through the MCP server (which dispatches synchronous tools off-thread) even
though the CLI and test-suite invocations (both main-thread) never
surfaced it; fixed via `gmsh.initialize(interruptible=False)`.

**MCP server and Claude Code skills -- done, fulfilling this draft's own
"Adapters may be built later" allowance under the LLM-Agnostic principle.**
A new, separate `printlab_mcp` package (own `pyproject.toml`
optional-dependency group, own console script) exposes `check`/`all`/
`orient`/`render`/`fea`/`doctor` as FastMCP tools; `printlab/` itself gains
zero new imports or dependencies from this -- `printlab_mcp` depends on
`printlab`, never the reverse, preserving "the repository must not depend
upon ... MCP" from this draft's Guiding Principles. Two Claude Code skills
(`.claude/skills/printlab-iterate`, `printlab-render`) drive the CLI
directly (not the MCP tools) with the same read-the-JSON, propose-a-CAD-edit
discipline as `AGENTS.md`.

**Containerization was investigated (not just left unscoped) and punted
deliberately** -- see `docs/environment.md`'s "What's deliberately out of
scope for v0.1" for the full reasoning; summary: the deterministic core
(layer 1) is already confirmed multi-arch (`cadquery-ocp`/`vtk` both publish
`linux/aarch64` wheels, so `uv.lock` alone reproduces it on Apple Silicon or
amd64), but today's three slicers (layer 2) are not -- Bambu Studio and
OrcaSlicer ship x86_64-only Linux AppImages, and PrusaSlicer has no Linux
binary at all outside Flatpak. Since the mesh-derived printability checks
that matter most don't need a slicer (`printlab check`), this was judged
safe to defer rather than urgent. Slic3r was evaluated as a "more portable"
alternative and rejected -- it's PrusaSlicer's unmaintained ancestor (last
release 1.3.0, 2018), strictly worse. If revisited, the recommended shape is
a multi-arch `printlab-core` image (no slicer) plus a separate amd64-only
`printlab-full` image bundling PrusaSlicer (which would also let CI finally
*run* the golden reproducibility tests instead of skipping them), with a
time-boxed spike on **CuraEngine** -- a standalone headless C++ console
engine, architecturally a much better containerization fit than a GUI
slicer's CLI mode -- as the path to a multi-arch *full* image if that
becomes worth pursuing.

---

# Vision

PrintLab is **not** an AI CAD assistant.

PrintLab is a deterministic engineering environment that allows humans and AI coding agents to cooperatively design, evaluate, and iterate mechanical parts intended for additive manufacturing.

The repository should expose a clean set of CLI tools and Python APIs that perform engineering tasks reproducibly.

An LLM is **one possible client** of this environment.

The engineering environment itself is the product.

---

# Core Philosophy

The repository should be designed around one central idea:

> **The engineering pipeline owns the truth. The LLM owns proposals.**

Engineering software should produce deterministic artifacts.

LLMs should read those artifacts, suggest changes, modify CAD source, and rerun the pipeline.

At no point should engineering correctness depend on an LLM.

---

# Guiding Principles

## 1. Deterministic First

Every engineering operation must be executable without an LLM.

Examples:

- build CAD
- export STEP
- export STL
- analyze mesh
- repair mesh
- search orientations
- slice
- analyze G-code
- compute printability metrics
- generate reports

---

## 2. Modular

Each engineering capability should be an independent Python module with a stable API.

Example

```python
mesh.analyze(...)
mesh.repair(...)
slice.run(...)
slice.evaluate(...)
```

Avoid giant classes.

Avoid hidden state.

Prefer small functional interfaces.

---

## 3. Structured Artifacts

Engineering tools communicate primarily through machine-readable artifacts.

Examples:

```
mesh_report.json
slice_report.json
gcode_report.json
printability_report.json
```

Markdown and HTML reports are secondary human-facing outputs.

---

## 4. LLM Agnostic

The repository must not depend upon:

- GPT
- Claude
- Gemini
- Ollama
- MCP
- LangGraph
- AutoGen

Adapters may be built later.

The engineering layer should remain useful forever.

---

## 5. Reproducible

Given:

- identical CAD source
- identical printer profile
- identical material profile
- identical slicer version

the repository should generate identical engineering artifacts.

---

# High-Level Architecture

```
              Human

                 │

          Coding Agent
       (optional client)

                 │

          PrintLab CLI/API

                 │

     ----------------------------

       CAD

       Mesh

       Slice

       G-code

       Evaluation

       Reports

       Profiles

     ----------------------------

                 │

      External Engineering Tools

       build123d
       CadQuery
       OpenSCAD
       Bambu Studio
       PrusaSlicer
       trimesh
       MeshLab
       Blender
       CalculiX
```

Notice that the coding agent is **outside** the engineering stack.

It merely invokes tools.

---

# Initial Repository Layout

```
printlab/

    cad/

    mesh/

    slice/

    gcode/

    eval/

    report/

    profiles/

    cli/

tests/

examples/

docs/

scripts/

tools/

AGENTS.md

README.md

pyproject.toml
```

---

# Expanded Repository Layout

```
printlab/

    cad/

        base.py

        build123d.py

        cadquery.py

        openscad.py

        export.py

    mesh/

        analyze.py

        repair.py

        orient.py

        manifold.py

    slice/

        base.py

        bambu.py

        prusaslicer.py

    gcode/

        parser.py

        metrics.py

    eval/

        printability.py

        scoring.py

    report/

        markdown.py

        html.py

    profiles/

        printers/

        materials/

        processes/

    cli/

        main.py

examples/

    calibration_cube/

    bracket/

    enclosure/

    hook/

tests/

docs/

scripts/
```

---

# External Tooling

PrintLab wraps best-in-class engineering tools.

It does not attempt to replace them.

## CAD

Initial backend (choose one)

- build123d (preferred)
- CadQuery

Future

- OpenSCAD
- FreeCAD

---

## Mesh

- trimesh
- MeshLabServer
- Blender (headless)

---

## Slicers

Initial implementation should support **two slicers**.

### Bambu Studio CLI

Primary target for Bambu printer owners.

Supports:

- Bambu printer profiles
- filament profiles
- 3MF project generation
- orientation
- slicing

### PrusaSlicer CLI

Provides:

- generic open slicing backend
- architecture validation
- portability

The goal is to force a clean abstraction rather than coupling the system to a single slicer.

Future:

- OrcaSlicer

---

## Simulation (Future)

- CalculiX
- Elmer FEM
- FreeCAD FEM

---

# Canonical Pipeline

```
CAD Source

↓

Build Geometry

↓

STEP

↓

STL

↓

Mesh Analysis

↓

Mesh Repair

↓

Orientation Search

↓

Slice

↓

G-code Analysis

↓

Evaluation

↓

Reports
```

Every stage must be independently executable.

---

# CLI

Examples

```
printlab build examples/hook

printlab mesh examples/hook

printlab slice examples/hook

printlab gcode examples/hook

printlab evaluate examples/hook

printlab report examples/hook

printlab all examples/hook
```

---

# Generic Slicer Interface

PrintLab should expose a slicer-independent API.

Example

```python
class SliceRequest:

    input_model: Path

    output_dir: Path

    printer_profile: Path

    material_profile: Path

    process_profile: Path | None

    quality_preset: str | None

    supports: bool | None

    brim: bool | None

    infill_percent: float | None

    layer_height_mm: float |None


class SliceResult:

    success: bool

    backend: str

    backend_version: str

    gcode_path: Path | None

    project_path: Path | None

    report_path: Path

    warnings: list[str]

    metrics: dict
```

Each backend is responsible for translating this request into its native CLI.

---

# Output Artifacts

Every run should produce a deterministic output directory.

Example

```
output/

    part.step

    part.stl

    part.3mf

    mesh_report.json

    slice_report.json

    gcode_report.json

    printability_report.json

    report.md

    report.html
```

These artifacts are the primary interface consumed by coding agents.

---

# JSON Design

Reports should be structured.

Example

```json
{
  "passed": true,
  "warnings": [
    "Minimum wall thickness is close to nozzle diameter."
  ],
  "metrics": {
    "min_wall_mm": 1.2,
    "support_volume_cm3": 5.8,
    "estimated_time_hr": 2.3
  }
}
```

Avoid free-form prose.

Prefer numeric metrics.

---

# Printability Metrics

## Geometry

- manifold
- watertight
- self intersections
- disconnected shells
- bounding box
- surface area
- volume

---

## Manufacturing

- minimum wall thickness
- bridge lengths
- unsupported spans
- overhang histogram
- embossed text height
- engraved text depth
- minimum feature size

---

## Slicing

- estimated print time
- filament length
- filament mass
- support volume
- support percentage
- layer count
- first-layer area
- build volume utilization

---

## Machine Constraints

- printer build volume
- nozzle diameter
- compatible layer heights
- minimum printable feature

---

# Profiles

Profiles should be version-controlled.

```
profiles/

    printers/

        bambu_a1.yaml

        bambu_x1c.yaml

        prusa_mk4s.yaml

    materials/

        pla.yaml

        petg.yaml

        abs.yaml

    processes/

        draft.yaml

        quality.yaml

        strength.yaml
```

Profiles contain engineering parameters only.

---

# Scoring

PrintLab should compute an overall printability score.

Example

```
Overall Score

95 / 100

Warnings

2

Failures

0
```

This score is intended for optimization by agents.

---

# AGENTS.md

Include explicit instructions for coding agents.

Example guidance:

- Never edit generated artifacts.
- Edit only CAD source.
- Always rerun evaluation after changes.
- Compare reports numerically.
- Explain why a change improved the design.
- Preserve deterministic outputs.
- Do not bypass engineering validation.

---

# Future Agent Loop

The deterministic pipeline should make this trivial:

```
repeat

    edit CAD

    build

    evaluate

    compare scores

until score no longer improves
```

This orchestration should live outside the engineering modules.

---

# Future Vision Loop

```
CAD

↓

Render

↓

Vision Model

↓

Suggested Improvements

↓

Engineering Validation

↓

Iteration
```

Visual correctness is advisory.

Engineering metrics are authoritative.

---

# Future FEA

Eventually support:

- cantilever estimation
- snap-fit analysis
- static loading
- anisotropy estimation
- orientation optimization

Simulation results become structured artifacts just like slicer reports.

---

# Testing Philosophy

Every module should include:

- unit tests
- deterministic outputs
- golden reference artifacts

Integration tests should be separated from unit tests.

Unit tests should never require external slicers.

Integration tests should automatically execute if Bambu Studio and/or PrusaSlicer are installed.

CI should gracefully skip unavailable slicer integrations while still exercising all deterministic code.

---

# Non-Goals

PrintLab is not attempting to:

- replace CAD software
- replace slicers
- replace FEM software
- become a chatbot
- require cloud AI
- depend upon any particular LLM vendor

Instead, it provides a stable engineering substrate that any future coding agent can operate.

---

# Initial Milestone (v0.1)

Deliverables:

- Python package (`pyproject.toml`)
- Typer-based CLI
- Environment specification
- Printer/material/process profile system
- One CAD backend (build123d preferred)
- Generic slicer abstraction
- Bambu Studio CLI adapter
- PrusaSlicer CLI adapter
- Mesh analysis using `trimesh`
- Structured JSON reports
- Markdown reports
- Two example parametric models
- Unit tests
- Optional slicer integration tests
- GitHub Actions CI for deterministic components

No LLM integration is required.

The primary success criterion is a reproducible engineering environment that emits machine-readable artifacts suitable for consumption by any future coding agent.
