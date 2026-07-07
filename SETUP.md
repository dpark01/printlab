# PrintLab
## A Reproducible Agentic Engineering Environment for 3D-Printable Mechanical Design

**Version:** 0.2 Draft

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
