# AGENTS.md

PrintLab's central idea: **the engineering pipeline owns the truth; the LLM
owns proposals.** Nothing here asks you to trust your own geometric or
manufacturing intuition over what the pipeline measures — it asks you to
read the pipeline's output and propose changes to CAD source in response.

## Environment bootstrap

Do not assume the native toolchain is present just because `uv sync` succeeds.
Before work that requires the full pipeline, run `uv run printlab doctor
--strict`. If it fails, run the repository's full-stack installer and then
rerun the strict check:

```bash
scripts/setup-macos.sh  # macOS
scripts/setup-linux.sh  # x86_64 apt-based Linux and GitHub Actions
```

These scripts install all locked Python extras plus all native tools in
`tools.toml`: PrusaSlicer, Bambu Studio, OrcaSlicer, OpenSCAD, FreeCAD, and
CalculiX. They are the installation source of truth for both humans and CI;
CI must call the Linux script rather than carry a second inline recipe.
Missing tools are only an acceptable reason to use `printlab check` when the
task explicitly permits the slicer-free subset, not as a silent substitute
for bootstrapping the full stack.

## Operating rules

- **Edit only configured CAD source** (`[part].source`, usually
  `examples/*/part.py` or `examples/*/part.scad`, plus source-language include
  files). Never hand-edit anything
  under an `output/` directory — every file there is generated and will be
  silently overwritten (and `printlab all` deletes the output directory
  clean before regenerating it — see `printlab.pipeline.prepare_output_dir`).
- **Always rerun the full pipeline after a CAD change**
  (`printlab all examples/<part> --backend <backend>`) before drawing any
  conclusion. A stale `printability_report.json` from before your edit is
  not evidence about your edit.
- **Compare reports numerically, not visually.** Read the JSON artifacts
  (below), not `report.md` — the Markdown report is a secondary, human-facing
  rendering of the same numbers (see `printlab/reporting/markdown.py`).
- **Explain *why* a change improved (or didn't improve) a design** in terms
  of the specific metrics that moved, e.g. "wall thickness increase raised
  `filament_mass_g` by 12% but flipped `manifold_watertight` to PASS" — not
  "this looks better."
- **Do not bypass or reinterpret a FAIL.** If `printability_report.json`
  reports `status: "error"`, the part has a real problem; find the fix in
  CAD source rather than adjusting the evaluation thresholds to make the
  failure disappear.
- **Do not optimize the `provisional_score`.** `printability_report.json` now
  carries a `provisional_score` (0–100), but it is UNCALIBRATED and ships with
  `score_calibrated: false` (always, in v1) — a fixed, arbitrary per-check
  penalty for rough human triage only, not a real signal. Branch on
  `score_calibrated` if you need to know it's untrustworthy programmatically.
  An agent that hill-climbs this scalar is chasing artifacts of the penalty
  scheme, not real design improvements: reason about the individual `checks[]`
  and `metrics{}` instead. `scripts/optimize_loop.py` optimizes a specific
  named metric — never this score.
- **No slicer installed? Use `printlab check <example_dir>` instead of
  `all`.** It runs build -> mesh -> evaluate -> report with slicing skipped
  entirely — the mesh-derived checks (manifold, build-volume fit, wall
  thickness) still produce a real verdict; slicer-derived metrics (filament
  mass, print time, layer count) come back `null` in `metrics{}`, and the
  `layer_height_allowed` check degrades to a `warning`, not an error. `all`
  fails outright without a working slicer (`stage_slice` returns a
  `binary_not_found` error); `check` is the sanctioned way to iterate on CAD
  source without one.
- **Try `printlab orient <example_dir>` before manually second-guessing a
  part's build orientation.** It tries the 6 axis-aligned rotations of a
  built part and recommends one by an explicit tie-break chain (minimize
  overhang area, then maximize wall thickness, then minimize unsupported
  span — see `printlab/mesh/orientation.py`), not a weighted score. It is
  mesh-metrics-only (no re-slicing candidates) and not part of `printlab
  all`.
- **The sanctioned agent loop is `scripts/optimize_loop.py`, not an ad hoc
  edit/rerun cycle.** It implements `repeat: edit CAD -> build -> evaluate
  -> compare -> until the metric stops improving` as a pluggable
  `propose_edit(source, last_result) -> str | None` callback around the
  configured CadQuery or OpenSCAD source file and
  `printlab.pipeline.run_check`/`run_all`, with a documented stopping rule
  (no ERROR-level check remains and the target metric hasn't improved for
  `patience` iterations, or the proposer returns `None`, or `max_iters` is
  reached) and automatic CAD-source restore afterward.
- **Use `printlab render <example_dir>` to actually look at a part** instead
  of inventing ad hoc visualization code. It renders `part.stl` to PNGs from
  named presets (`--view iso/front/back/left/right/top/bottom`) or an
  arbitrary angle (`--elevation`/`--azimuth`), writing `render_report.json`
  (the deterministic camera metadata — never the PNG bytes themselves, which
  are matplotlib-version-dependent like `part.stl`) alongside `render_*.png`.
  Works with `--backend check`, so no slicer is needed.
- **`printlab fea <example_dir>` gives a rough structural estimate** —
  fixed-at-the-bed, one point load, linear-static, via CalculiX — but only
  for a part whose `printlab.toml` has an `[fea]` load case (today, only
  `examples/hook`). Requires the `fea` extra (`uv sync --extra fea`) and
  `ccx` installed (`printlab doctor` reports it). Treat `fea_report.json` as
  order-of-magnitude: the material constants behind it are literature
  placeholders, exactly as uncalibrated as `provisional_score` — see
  `docs/fea.md`.
- **PrintLab is also reachable via MCP and two Claude Code skills**
  (`printlab_mcp/`, `.claude/skills/`) — see `docs/mcp.md`. They're a thin,
  optional layer over this same CLI/pipeline, not a different source of
  truth.

## The artifact contract

Every stage writes one JSON file into the run's output directory
(`<example_dir>/output/<backend>/`, see `printlab.pipeline.ARTIFACT_FILENAMES`).
Every artifact shares the same envelope, defined once in
`printlab/schemas/common.py`:

```json
{
  "schema_version": "0.1.0",
  "status": "ok | warning | error",
  "errors": [
    {"code": "...", "message": "...", "stage": "...", "context": {}}
  ]
}
```

Branch on `status`/`errors[]`, not on parsing prose out of `message`. Full
JSON Schemas for every artifact are committed under `docs/schemas/*.json`
(regenerate with `scripts/generate_schemas.py` after any model change).

**Which metrics are exact vs. advisory:**

- `mesh_report.json` (volume, area, manifold/watertight, bbox) and
  `gcode_report.json`'s `layer_count`, `filament_length_mm`,
  `filament_mass_g` are computed independently by PrintLab and are exact —
  never scraped from a slicer's own report (see `printlab/gcode/parser.py`
  docstring for why: a slicer's self-reported metrics have been observed to
  be zeroed/unreliable in practice).
- `gcode_report.json`'s `estimated_time_s` is the one exception: simulating
  firmware motion planning to derive time independently is out of scope for
  v0.1, so this field is parsed from the slicer's own comment and should be
  treated as advisory.
- `run_manifest.json` records tool versions and input/profile content
  hashes. Two runs with identical CAD source, profiles, and pinned tool
  versions must produce identical `mesh_report.json` / `slice_result.json` /
  `gcode_report.json` / `printability_report.json` (byte-identical after
  normalization — see `printlab/determinism.py`); `run_manifest.json` is
  what lets you diff *why* two runs differ instead of guessing.

## Non-goals (don't propose these as fixes)

A *calibrated* composite printability score is deliberately out of scope. The
report does expose a `provisional_score` (0–100) with `score_calibrated: false`
— but that flag is `false` in every v1 report on purpose, and the score is a
fixed, arbitrary per-check penalty (see `printlab/schemas/evaluation.py`), not
a data-justified weighting. Treat it as triage-only and never as an
optimization target: an uncalibrated scalar is noise an agent would learn to
game rather than a real signal. Real calibration needs data — more example
parts spanning known failure modes (`examples/thinwall`, `examples/bridge`
exist for exactly this), ideally real print outcomes — before weights mean
anything and `score_calibrated` can flip to `true`. Don't invent your own
weighted score inside an evaluation check either; reason about the individual
`checks[]`/`metrics{}` instead.

Full containerization (a multi-arch Docker image bundling a slicer) is also
out of scope for now: the deterministic core is already multi-arch via
`uv.lock` (see `docs/environment.md`), but the slicers are not, and
packaging just the core without a slicer wasn't judged worth the extra
layer yet. Note that orientation search, mesh repair, and the manufacturing
metrics (minimum wall thickness, overhang histograms, bridge spans) are all
already implemented (`printlab/mesh/`) — don't propose adding them.
