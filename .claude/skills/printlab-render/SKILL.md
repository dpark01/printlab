---
description: >
  Render a PrintLab part to PNG images from standard or custom camera angles
  and inspect it visually. Use when the user asks to "show me", "render", or
  "look at" a part under examples/<name>/.
allowed-tools: Bash(uv run printlab*), Read
---

# PrintLab render

1. Ensure a mesh exists: `uv run printlab check examples/<name>` (no slicer
   needed).
2. Render:
   `uv run printlab render examples/<name> --backend check --view iso --view front --view top`
   (or `--elevation <deg> --azimuth <deg>` for a specific angle).
3. Read `render_report.json` for the exact camera params, then view the
   `render_*.png` files and describe what you see.
