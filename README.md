# PrintLab

A deterministic engineering environment for 3D-printable mechanical design.

PrintLab is **not** an AI CAD assistant. It's a CLI/Python pipeline that
builds parametric CAD source, slices it, and emits structured JSON reports —
usable identically by a human or a coding agent. The central idea:

> **The engineering pipeline owns the truth. The LLM owns proposals.**

Engineering correctness never depends on an LLM. An agent reads the JSON
artifacts below, proposes a change to CAD source, and reruns the pipeline —
the pipeline is the arbiter, not the agent. See [`SETUP.md`](SETUP.md) for
the original design doc and [`AGENTS.md`](AGENTS.md) for the rules an agent
follows when working in this repo.

## Quickstart

```bash
uv sync                      # Python deps (CadQuery, trimesh, ...)
uv run printlab doctor       # check native slicer versions against tools.toml
uv run printlab all examples/bracket --backend prusaslicer
```

This builds the example L-bracket, slices it, and writes every artifact to
`examples/bracket/output/prusaslicer/`, including a human-readable
`report.md`. Swap `--backend bambu` or `--backend orcaslicer` to slice with
Bambu Studio or OrcaSlicer instead — the same CAD source, profiles, and
evaluation logic apply to all three.

No slicer installed? `uv run printlab check examples/hook` runs build ->
mesh -> evaluate -> report with slicing skipped entirely — the mesh-derived
printability checks (manifold, build-volume fit, wall thickness) still
produce a real pass/warn/fail verdict; slicer-derived metrics (filament
mass, print time) come back null. `uv run printlab orient examples/hook`
tries the 6 axis-aligned rotations of a built part and recommends one by an
explicit tie-break chain over the overhang/wall-thickness/bridge metrics.

See [`docs/environment.md`](docs/environment.md) for full environment setup
(macOS/Linux setup scripts, the three-layer reproducibility model).

## Pipeline

```
CAD source (part.py)
    -> build (CadQuery)          -> part.step, part.stl
    -> mesh analysis (trimesh)   -> mesh_report.json
    -> slice (Bambu | Prusa)     -> slice_result.json, G-code
    -> gcode analysis (ours)     -> gcode_report.json      <- authoritative metrics
    -> evaluate                  -> printability_report.json
    -> report                    -> report.md, report.html
```

Every run also writes `run_manifest.json`: tool versions, input/profile
content hashes, and a content hash of the run's own artifacts — the
provenance record that makes two runs comparable and an agent loop auditable.

## Artifacts

| File                        | Produced by            | Notes                                          |
|------------------------------|-------------------------|-------------------------------------------------|
| `part.step` / `part.stl`     | `printlab.cad`          | Pinned tessellation deflection                  |
| `mesh_report.json`           | `printlab.mesh`         | Geometry only: manifold, bbox, volume, area     |
| `mesh_repair_report.json`    | `printlab.mesh`         | Explicit-only (`printlab repair`), not in `all` |
| `orientation_search_report.json` | `printlab.mesh`     | Explicit-only (`printlab orient`), not in `all` |
| `slice_result.json`          | `printlab.slicing`      | Backend-specific; `resolved_settings` is hashed |
| `gcode_report.json`          | `printlab.gcode`        | Authoritative — see caveat below                |
| `printability_report.json`   | `printlab.evaluation`   | Raw metrics + pass/warn/fail checks, no score   |
| `report.md` / `report.html`  | `printlab.reporting`    | Secondary, human-facing rendering (same data)   |
| `run_manifest.json`          | `printlab.provenance`   | Tool versions + content hashes                  |

All artifacts share one envelope (`schema_version` / `status` / `errors[]`);
full JSON Schemas are committed under `docs/schemas/*.json`. See
[`AGENTS.md`](AGENTS.md) for the complete artifact contract, including which
fields are exact vs. advisory.

**Caveat:** `gcode_report.json`'s metrics — layer count, filament length,
filament mass — are computed by PrintLab directly from G-code motion
commands, never trusted from a slicer's own report (Bambu Studio's CLI has
been observed reporting zeroed filament weight/density on a real slice). The
one exception is `estimated_time_s`, parsed from the slicer's own comment
since independently simulating firmware motion timing is out of scope for
v0.1 — treat it as advisory, unlike every other field.

## Design deviations from the original draft

`SETUP.md` is the original v0.2 design doc. The as-built v0.1 differs from it
in a few deliberate ways — most notably: reproducibility is defined in three
tiers rather than claimed as byte-identical (slicers embed timestamps; see
`printlab/determinism.py`), there is no composite printability score, and
slicer metrics are always re-derived from G-code rather than trusted from a
slicer's own report. These are explained in-line in the relevant module
docstrings (`printlab/determinism.py`, `printlab/schemas/evaluation.py`,
`printlab/gcode/parser.py`) rather than duplicated here.

## Status

v0.1 shipped one example part (`examples/bracket`), two working slicer
backends (PrusaSlicer, Bambu Studio), and the full pipeline above. Since
then: a second example (`examples/hook`, with a real cantilevered
overhang), `quality`/`strength` process profiles alongside `draft`, the
HTML report, basic mesh repair (`printlab repair`), and a third backend
(OrcaSlicer, added after an evidence-based spike — see
`printlab/slicing/orcaslicer.py`).

Manufacturing-tractability metrics (minimum wall thickness, an overhang
histogram, unsupported-span/"bridge" detection) are done and always present
in `mesh_report.json`. Orientation search (`printlab orient`) is also done:
it tries the 6 axis-aligned rotations of a built part and recommends one by
an explicit tie-break chain (minimize overhang, then maximize wall
thickness, then minimize unsupported span — see
`printlab/mesh/orientation.py`), not a weighted score. Concretely, it cuts
`examples/hook`'s ~32mm default-orientation cantilever to 20mm. `printlab
check` runs build -> mesh -> evaluate -> report with slicing skipped
entirely, so the mesh-derived printability checks are reachable with no
slicer installed (`printlab.pipeline.run_check`). Two further example parts
(`examples/thinwall`, `examples/bridge`) exist purely as future calibration
data — see below. `scripts/optimize_loop.py` implements the agent
optimization loop this project originally specified (`repeat: edit CAD ->
build -> evaluate -> compare -> until the metric stops improving`) as a
standalone script outside the engineering pipeline, with a pluggable
`propose_edit` callback (PrintLab itself never calls an LLM) and a
deterministic demo proposer so the loop runs and tests with zero LLM.

Unit tests need neither a CAD kernel nor a slicer; integration tests are
capability-gated — most need a real slicer binary and self-skip without one,
but the `check`/`orient`/optimize-loop tests need only a real CadQuery build
and always run in the heavy lane, since they exercise no slicer at all.

Deferred: a calibrated composite printability score — an uncalibrated
hand-weighted scalar would be noise an agent learns to game rather than a
real signal (see `printlab/schemas/evaluation.py`); it needs calibration
data (more example parts spanning known failure modes, ideally real print
outcomes) before picking weights, which is what `examples/thinwall` and
`examples/bridge` are for. Also deferred: full containerization. The
deterministic core (CadQuery/trimesh/PrintLab) is already multi-arch —
`cadquery-ocp` and `vtk` both publish `linux/aarch64` wheels, so `uv sync`
alone reproduces the environment on Apple Silicon or amd64 alike — but two
of the three slicers ship x86_64-only Linux binaries, so a slicer-bearing
image can't currently be multi-arch too. See
[`docs/environment.md`](docs/environment.md) for the full reasoning and the
path being considered (a headless CuraEngine spike) if that's revisited.
