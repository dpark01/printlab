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
scripts/setup-macos.sh        # macOS: complete Python + native stack
# scripts/setup-linux.sh      # x86_64 apt-based Linux: same stack used by CI
uv run printlab doctor --strict
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
`uv run printlab render examples/hook --view iso --view front --view top`
renders PNGs of the built part from named camera angles (or
`--elevation`/`--azimuth` for a custom one) — no slicer needed either. With
the `fea` extra and CalculiX installed, `uv run printlab fea examples/hook`
runs a rough linear-static structural estimate (see
[`docs/fea.md`](docs/fea.md)).

The setup scripts are the shared, pinned installation recipe for humans and
the GitHub Actions heavy job. See [`docs/environment.md`](docs/environment.md)
for prerequisites, platform support, and the three-layer reproducibility model.

CAD source is selected independently from the slicer backend in
`printlab.toml`. Existing `part.py` examples default to CadQuery; an OpenSCAD
part uses `cad_backend = "openscad"` and `source = "part.scad"`. Because
OpenSCAD cannot export STEP natively, PrintLab compiles CSG plus a reference
STL, requires FreeCAD to translate the CSG into one valid B-rep solid, and
rejects mesh fallbacks or geometry that differs from the OpenSCAD reference.
See `examples/openscad-plate` for a complete configuration and
[`docs/openscad.md`](docs/openscad.md) for the strict conversion contract,
compatibility repairs, and actionable failure guidance.

## Pipeline

```
CAD source (CadQuery .py | OpenSCAD .scad)
    -> build (selected CAD backend) -> cad_build_report.json, part.step, part.stl
    -> mesh analysis (trimesh)   -> mesh_report.json
    -> slice (Bambu | Orca | Prusa) -> slice_result.json, G-code
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
| `cad_build_report.json`       | `printlab.cad`          | CAD backend, dependencies, native versions, validation metadata |
| `part.step` / `part.stl`     | `printlab.cad`          | Pinned tessellation deflection                  |
| `mesh_report.json`           | `printlab.mesh`         | Geometry only: manifold, bbox, volume, area     |
| `mesh_repair_report.json`    | `printlab.mesh`         | Explicit-only (`printlab repair`), not in `all` |
| `orientation_search_report.json` | `printlab.mesh`     | Explicit-only (`printlab orient`), not in `all` |
| `render_report.json` / `render_*.png` | `printlab.rendering` | Explicit-only (`printlab render`); PNGs not hashed (like `part.stl`) |
| `fea_report.json`            | `printlab.fea`          | Explicit-only (`printlab fea`); needs `[fea]` in `printlab.toml` |
| `slice_result.json`          | `printlab.slicing`      | Backend-specific; `resolved_settings` is hashed |
| `gcode_report.json`          | `printlab.gcode`        | Authoritative — see caveat below                |
| `printability_report.json`   | `printlab.evaluation`   | Raw metrics + pass/warn/fail checks + an uncalibrated `provisional_score` |
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

## MCP & agent integration

An optional MCP adapter, `printlab_mcp`, exposes the pipeline (`check`, `all`,
`orient`, `render`, `doctor`) as Model Context Protocol tools for Claude Code
and other MCP clients. It's a one-way dependency — `printlab_mcp` depends on
`printlab`, never the reverse, and the core takes on no `fastmcp` or
agent-framework dependency. Install with `uv sync --extra mcp`; see
[`docs/mcp.md`](docs/mcp.md) for registration, the tool list, and the two
Claude Code skills (`printlab-iterate`, `printlab-render`).

## Design deviations from the original draft

`SETUP.md` is the original v0.2 design doc. The as-built v0.1 differs from it
in a few deliberate ways — most notably: reproducibility is defined in three
tiers rather than claimed as byte-identical (slicers embed timestamps; see
`printlab/determinism.py`), the composite printability score is explicitly
uncalibrated rather than a trusted single number (see `provisional_score`/
`score_calibrated` below), and slicer metrics are always re-derived from
G-code rather than trusted from a slicer's own report. These are explained
in-line in the relevant module docstrings (`printlab/determinism.py`,
`printlab/schemas/evaluation.py`, `printlab/gcode/parser.py`) rather than
duplicated here.

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
deterministic demo proposer so the loop runs and tests with zero LLM. A
third example, `examples/canoe` (a hollow superellipse hull with engraved
text), joined the golden/integration test suites — its engraved lettering
persistently trips the `min_wall_thickness` check via ray-cast noise on
sharp glyph corners, a known heuristic artifact rather than a real design
flaw (see `printlab/mesh/wall_thickness.py`). A fourth, `examples/benchy`
(the standard 3DBenchy torture-test hull, vendored as a CC0 STEP file rather
than built from primitives, sliced with a new supports-enabled `supports`
process profile), joined the build/slice integration coverage and the CI
smoke-build, but was deliberately kept out of `mesh`/`evaluate`/`check`/`all`
and the golden reproducibility test: its STEP-to-mesh tessellation produces
some zero-area triangles, and `estimate_min_wall_thickness_mm` doesn't guard
against the resulting NaN normals (`printlab/mesh/wall_thickness.py`'s
`unit_normals` division), which crashes ray casting outright with an
uncaught `rtree` error rather than degrading gracefully — a real bug,
distinct from (and more severe than) the OOM `ef974aa` fixed for canoe, left
as a known follow-up rather than fixed here. `build`/`slice`/`gcode` are
unaffected since they never call wall-thickness estimation.

`printlab render` (`printlab/rendering/`) offscreen-renders a built part to
PNGs via matplotlib/Agg — already a transitive dependency, so no new
install — from named presets or an arbitrary camera angle, alongside a
`render_report.json` recording the (deterministic) camera metadata; the PNG
bytes themselves are never hashed, the same treatment as `part.stl`.
`printlab fea` (`printlab/fea/`) adds a first, deliberately crude structural
capability: a linear-static analysis via CalculiX, meshing the part's STEP
export with Gmsh, on transversely-isotropic (build-direction-aware)
material properties — see [`docs/fea.md`](docs/fea.md) for the engine
rationale, the load-case format, and why its material constants are exactly
as uncalibrated as `provisional_score`.

Unit tests need neither a native CAD compiler nor a slicer; integration tests are
capability-gated — most need a real slicer binary and self-skip without one,
but the `check`/`orient`/optimize-loop tests need only a real CadQuery build
and always run in the heavy lane, since they exercise no slicer at all. The
heavy CI lane installs the pinned OpenSCAD/FreeCAD pair and runs the strict
bridge against `examples/openscad-plate`.

Partly landed: `printability_report.json` now exposes a `provisional_score`
(0–100), but it is explicitly UNCALIBRATED — it carries `score_calibrated:
false` in every v1 report and is a fixed, arbitrary per-check penalty for
rough triage only, not something to optimize (see `provisional_score` /
`score_calibrated` in `printlab/schemas/evaluation.py`). Still deferred: a
*calibrated* composite score. An uncalibrated hand-weighted scalar would be
noise an agent learns to game rather than a real signal; deriving trustworthy
weights (so `score_calibrated` can flip to `true`) needs calibration data
(more example parts spanning known failure modes, ideally real print
outcomes), which is what `examples/thinwall` and `examples/bridge` are for. Also deferred: full containerization. The
deterministic core (CadQuery/trimesh/PrintLab) is already multi-arch —
`cadquery-ocp` and `vtk` both publish `linux/aarch64` wheels, so `uv sync`
alone reproduces the environment on Apple Silicon or amd64 alike — but two
of the three slicers ship x86_64-only Linux binaries, so a slicer-bearing
image can't currently be multi-arch too. See
[`docs/environment.md`](docs/environment.md) for the full reasoning and the
path being considered (a headless CuraEngine spike) if that's revisited.
