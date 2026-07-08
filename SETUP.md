# PrintLab
## A Reproducible Agentic Engineering Environment for 3D-Printable Mechanical Design

**Version:** 0.2 Draft

---

# Implementation Status (as of 2026-07-07)

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

**Phase B -- manufacturing-tractability metrics (B.6-B.8 done, B.9 not started):**
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

## Not done -- a handoff for whoever (or whichever agent) picks this up next

This section is written so a fresh agent with no memory of prior sessions can
act on it directly: concrete files to create, what to reuse, and open
questions to resolve rather than assume.

### B.9 Orientation search -- not started

**Goal:** try several candidate rotations of a built part, re-run mesh
analysis (and optionally slicing) for each, and recommend the best
orientation by the metrics that already exist -- no new hard-geometry work
needed, this is an orchestration layer over B.6-B.8.

**Why it matters concretely:** `examples/hook` was deliberately designed so
its natural CAD orientation (mounting plate vertical, as used) has a bad
~32mm unsupported cantilever (see `max_unsupported_span_mm` in its
`mesh_report.json`). Rotating the part 90 degrees about X so the arm points
straight up during printing should eliminate that overhang almost entirely.
Demonstrating this concretely on the hook is the natural acceptance test for
this feature.

**Suggested approach:**
1. New module `printlab/mesh/orientation.py` (or a `printlab/orientation/`
   package if it grows): a function like
   `search_orientations(mesh, candidate_rotations) -> list[OrientationCandidate]`
   that, for each candidate rotation (a set of `(axis, degrees)` or a
   rotation matrix), applies the rotation to a *copy* of the mesh (trimesh
   supports `mesh.copy()` + `mesh.apply_transform()`), re-runs
   `printlab.mesh.overhangs.compute_overhangs`,
   `printlab.mesh.wall_thickness.estimate_min_wall_thickness_mm`, and
   `printlab.mesh.bridges.estimate_max_unsupported_span_mm` against the
   rotated copy (mesh volume/surface area are rotation-invariant, no need to
   recompute), and records the results.
2. A simple, explicit candidate set is enough for v0.1: the 6 axis-aligned
   orientations (rotations that put each of +X/-X/+Y/-Y/+Z/-Z as the "up"
   direction) rather than a full continuous search -- this is cheap (6
   evaluations) and covers the common real cases including the hook's fix.
3. Comparison/ranking: with no composite score (see C.10), rank candidates
   by a simple, explicit tie-break chain documented in code, e.g. minimize
   `overhang_area_mm2` first, then maximize `min_wall_thickness_mm`, then
   minimize `max_unsupported_span_mm` -- do not invent a weighted scalar
   here; that is exactly what C.10 is for once there's calibration data.
4. New schema: an `OrientationSearchReport` (or similar) in
   `printlab/schemas/` listing each candidate's rotation + metrics + which
   one was selected and why, following the existing artifact envelope
   (`schema_version`/`status`/`errors[]` -- see `printlab/schemas/common.py`).
   Regenerate `docs/schemas/*.json` via `scripts/generate_schemas.py` after
   adding it, or `tests/unit/test_schemas.py::test_committed_json_schemas_are_up_to_date`
   will fail CI.
5. Pipeline/CLI wiring: a new `printlab.pipeline.stage_orientation_search`
   and a `printlab orient <example_dir>` command, following the existing
   stage pattern in `printlab/pipeline.py` (see `stage_mesh`/`stage_repair`
   for the shape: compute, write JSON atomically via `_write_json_atomic`,
   return the report). Whether to also re-slice each candidate (not just
   re-analyze the mesh) is an open question -- re-slicing 6x is slower but
   would let ranking include `estimated_time_s`/support volume from
   `gcode_report.json` too; a reasonable v1 scope is mesh-metrics-only
   ranking, with a note that slicing the winning orientation to confirm is
   a natural follow-up.
6. Tests: unit tests using synthetic meshes with a known-bad default
   orientation (e.g. reuse the suspended-shelf rig from
   `tests/unit/test_mesh_overhangs.py`/`test_mesh_bridges.py`, which has an
   obvious best rotation), plus an integration-style check against the real
   `examples/hook` part confirming the search recommends rotating away from
   the default orientation.

### Phase C -- scoring & the agent loop -- not started

**C.10: a calibrated composite printability score.** Deliberately deferred
in v0.1 (see `printlab/schemas/evaluation.py` docstring) because an
uncalibrated hand-weighted scalar is noise an agent would learn to game
rather than a real signal. Do not add this by just picking weights that
"feel right" -- that repeats the mistake this draft's v0.1 already backed
away from. What "calibration data" concretely means: run the pipeline
across a range of example parts (more than the current two) and, ideally,
real print outcomes (did it actually print successfully?), then fit or
justify weights against that data. Practically, this probably wants a third
and fourth example part first (e.g. something with a known-bad wall
thickness, something requiring real support material) to have enough
variety to calibrate against. Until then, the individual metrics/checks in
`printability_report.json` remain the source of truth.

**C.11: an agent optimization loop.** The loop this draft originally
specified (`repeat: edit CAD -> build -> evaluate -> compare -> until score
no longer improves`) lives *outside* the engineering modules by this
draft's own design rule -- it should be a new orchestration script or CLI
command (e.g. `printlab optimize` or a separate `scripts/optimize_loop.py`),
not inside `printlab/pipeline.py`, and it must not itself become the source
of engineering truth. Concretely it needs: (a) a way to propose a CAD-source
edit (this is where an LLM/agent plugs in -- PrintLab itself stays
LLM-agnostic per its core philosophy, so this orchestration layer should
accept a pluggable "propose an edit" callback rather than hard-coding a
model call), (b) re-running `printlab.pipeline.run_all` after each edit, and
(c) a stopping rule. A stopping rule can start simple even without C.10 --
e.g. "stop when no ERROR-level check remains and the last N iterations
didn't reduce `filament_mass_g`/improve the specific metric you're
optimizing" -- a single composite score makes this cleaner but isn't a hard
prerequisite.

### Phase D and beyond -- not yet scoped in detail

A vision loop, FEA, and containerization remain as originally drafted below
this section, with one refinement worth recording: a vision-*capable* coding
agent already has the "vision model" built into itself (it can view an image
via its own tool use). What Phase D actually needs from PrintLab is
therefore likely just a cheap `render` capability (CAD/mesh -> a PNG, e.g.
via `trimesh.Scene.save_image()` or a CadQuery/OCP viewport export), not a
bespoke vision-model API integration -- the "loop" part (agent looks,
proposes, validates, iterates) is then just an agent using that render
alongside the existing JSON artifacts, which already works today with zero
additional PrintLab infrastructure once `render` exists. This makes a
`render` stage a candidate to pull forward ahead of the rest of Phase D if
it becomes useful sooner (it's cheap, mechanical work comparable to Phase A
items, not a big lift like FEA or containerization).

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
