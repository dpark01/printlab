# Environment & Reproducibility

PrintLab's reproducibility contract (see `printlab/determinism.py` for the
formal Tier 1/2/3 definitions) rests on three layers. Only layer 1 can be
captured in a single lockfile — this document covers all three.

## Layer 1: Python libraries

Source of truth: `pyproject.toml` + `uv.lock` (pinned with hashes) +
`.python-version` (3.12).

```bash
uv sync
```

reproduces the exact environment anywhere `uv` runs, including `cadquery` /
`cadquery-ocp` (OpenCascade via prebuilt wheels — no conda required), `trimesh`,
`pydantic`, and `typer`.

A `requirements.txt` is also committed (generated via `uv export
--no-hashes -o requirements.txt`) for plain-`pip` installs. It's a derived
file — regenerate it whenever `uv.lock` changes; don't hand-edit it.

## Layer 2: Native slicers

Slicer binaries can't live in a Python lockfile. `tools.toml` declares the
pinned version of each; `printlab doctor` compares your installed versions
against those pins:

```bash
uv run printlab doctor
```

A clean `doctor` run is a pre-flight check, not the reproducibility contract
itself — what actually matters is that the *resolved* version recorded in
each run's `run_manifest.json` matches across runs/machines you're comparing.

**Setup:**

- macOS: `scripts/setup-macos.sh` (installs both slicers via Homebrew casks)
- Linux: `scripts/setup-linux.sh` (PrusaSlicer via Flatpak — it publishes no
  Linux binary on GitHub releases; Bambu Studio via a pinned AppImage URL)

**Why Bambu Studio's native profile resolution is not fully self-contained:**
its preset JSON files use an `inherits` chain resolved against a system
profile database bundled *inside the installed application*, not from the
committed `profiles/native/bambu/*.json` file alone. This means Tier-1
reproducibility for the Bambu backend additionally depends on both machines
running the pinned BambuStudio version — which is exactly why `tool_versions`
in `run_manifest.json` records it. PrusaSlicer's native `.ini` bundles don't
have this issue: they're flat, fully self-contained key/value files PrintLab
authored itself.

## Layer 3: CAD software

CadQuery is a Python library, so it's covered by layer 1. A future non-Python
CAD backend (OpenSCAD, FreeCAD) would join layer 2 instead.

## What's deliberately out of scope for v0.1

Full turnkey containerization (a `Dockerfile`/devcontainer wrapping all three
layers) is a natural next step for portability, but is deferred: slicers pull
in GUI/GL dependencies that are awkward to containerize cleanly, and the
setup-scripts-plus-`doctor` approach above already gets a new machine to a
known, checkable state. Revisit this once the vertical slice has grown enough
to justify the extra packaging work.
