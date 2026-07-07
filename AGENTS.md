# AGENTS.md

PrintLab's central idea: **the engineering pipeline owns the truth; the LLM
owns proposals.** Nothing here asks you to trust your own geometric or
manufacturing intuition over what the pipeline measures — it asks you to
read the pipeline's output and propose changes to CAD source in response.

## Operating rules

- **Edit only CAD source** (`examples/*/part.py`). Never hand-edit anything
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
- **There is no composite score to optimize.** `printability_report.json`
  intentionally has no single 0–100 number in v0.1 (see `SETUP.md`
  deviations) — reason about the individual `checks[]` and `metrics{}`
  instead of hill-climbing a scalar.

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

Orientation search, mesh repair, a composite printability score, and
manufacturing metrics that need real geometry research (minimum wall
thickness, overhang histograms, bridge spans) are deliberately out of scope
for v0.1 — see `SETUP.md`. Don't add ad-hoc versions of these inside an
evaluation check; if one is genuinely needed, it belongs as a new pipeline
stage with its own tests, not a special case bolted onto CAD source.
