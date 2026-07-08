---
description: >
  Evaluate and iteratively improve a PrintLab part. Use when the user asks to
  check, fix, improve, or iterate on a part under examples/<name>/ -- e.g.
  "is examples/hook printable?", "improve the canoe's wall thickness",
  "why is this part failing?". Runs the deterministic pipeline, reads the
  JSON artifacts, and proposes CAD-source edits per AGENTS.md.
allowed-tools: Bash(uv run printlab*), Read, Edit
---

# PrintLab iterate

You improve a part by reading the pipeline's artifacts -- never by eyeballing.
The pipeline owns the truth; you own proposals (see AGENTS.md).

## Current state
Slicer availability:
!`uv run printlab doctor`

## Procedure
1. **Evaluate.** If a slicer is available, run
   `uv run printlab all examples/<name> --backend <backend>`; otherwise run
   `uv run printlab check examples/<name>`.
2. **Read the JSON, not the Markdown.** Open
   `examples/<name>/output/<backend|check>/printability_report.json`. Branch
   on `status` and each `checks[].status`. Note `provisional_score` is
   UNCALIBRATED (`score_calibrated: false`) -- do NOT optimize it; reason
   about `checks[]` instead.
3. **Orientation.** If overhangs/unsupported spans look bad, run
   `uv run printlab orient examples/<name>` and read `selection_reason`.
4. **Look at it.** Run
   `uv run printlab render examples/<name> --view iso --view front --view top`
   and view the `render_*.png` files.
5. **Propose a CAD edit** to `examples/<name>/part.py` ONLY (never edit
   output/).
6. **Rerun** the same command and **compare metrics numerically** -- e.g.
   "raised min_wall_thickness_mm 0.24->0.81, flipped min_wall_thickness to
   PASS."
7. **Do not bypass a FAIL** by loosening thresholds. Stop when no ERROR
   check remains and the target metric stops improving.
