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

## Layer 2: Native tools

Slicer and external CAD binaries can't live in a Python lockfile. `tools.toml`
declares the pinned version of each; `printlab doctor` compares your installed
versions against those pins:

```bash
uv run printlab doctor
```

A clean `doctor` run is a pre-flight check, not the reproducibility contract
itself — what actually matters is that the *resolved* version recorded in
each run's `run_manifest.json` matches across runs/machines you're comparing.

**Setup:**

- macOS: `scripts/setup-macos.sh` (installs all three slicers plus OpenSCAD and
  FreeCAD via Homebrew casks)
- Linux: `scripts/setup-linux.sh` (PrusaSlicer via Flatpak — it publishes no
  Linux binary on GitHub releases; Bambu Studio and OrcaSlicer via pinned
  AppImage URLs; OpenSCAD via the distribution package; pinned FreeCAD via its
  official x86_64/aarch64 AppImage)

**Why Bambu Studio's (and OrcaSlicer's) native profile resolution is not
fully self-contained:** their preset JSON files use an `inherits` chain
resolved against a system profile database bundled *inside the installed
application*, not from the committed `profiles/native/bambu/*.json` file
alone. This means Tier-1 reproducibility for these backends additionally
depends on both machines running the same pinned application version —
which is exactly why `tool_versions` in `run_manifest.json` records it.
PrusaSlicer's native `.ini` bundles don't have this issue: they're flat,
fully self-contained key/value files PrintLab authored itself.

**Why there are three backends, not two:** PrusaSlicer is the reference/CI
backend (stable, deterministic, no per-machine profile dependency). Bambu
Studio and OrcaSlicer both serve the user's actual Bambu printer. OrcaSlicer
was added after an evidence-based spike (see `printlab/slicing/orcaslicer.py`
docstring) found its CLI and G-code conventions are nearly identical to
Bambu Studio's — the original case for adding it ("richer CLI") didn't hold
up under direct testing — but it bundles a substantially broader vendor
profile library while remaining Bambu-compatible, which is a real, verified
reason to keep both around rather than picking one.

## Layer 3: CAD source backends

CadQuery is a Python library, so it is covered by layer 1. OpenSCAD source uses
the layer-2 `openscad` executable, then FreeCAD as a strict CSG-to-B-rep STEP
bridge. The bridge rejects FreeCAD mesh/placeholder fallbacks, requires exactly
one valid closed solid, and compares the canonical OCP tessellation against an
OpenSCAD reference STL before accepting the build. Actual versions and
comparison metrics are recorded in `cad_build_report.json`; the native versions
also participate in build freshness and `run_manifest.json` provenance.

## What's deliberately out of scope for v0.1

Full turnkey containerization (a `Dockerfile`/devcontainer wrapping all three
layers) is a natural next step for portability, but is deferred, and the
reasoning has sharpened since this was first written: it isn't that
containerizing the whole stack is hard in general -- layer 1 turns out to
already be multi-arch (see below) -- it's specifically that layer 2's
slicers aren't, and the checks that most matter (manifold, build-volume fit,
minimum wall thickness -- everything mesh-derived) don't need a slicer at
all (see `printlab check` / `printlab.pipeline.run_check`). The
setup-scripts-plus-`doctor` approach above already gets a new machine to a
known, checkable state in the meantime.

**Layer 1 is already multi-arch, concretely verified:** `cadquery-ocp`
(`manylinux_2_31_aarch64`) and `vtk` (`manylinux_2_28_aarch64`) both publish
`linux/aarch64` wheels for the pinned Python version, alongside the existing
`linux/x86_64` wheels -- so `uv sync` alone reproduces the full Python
environment on Apple Silicon or amd64 Linux identically, no conda and no
per-arch special-casing needed. A container for this layer would only add
one real thing: pinning the OS/GL-shared-library layer that OCP/vtk link
against at import time (undocumented today; CI's `ubuntu-latest` happens to
have enough of it installed already).

**Layer 2's slicers are the actual constraint, not layer 1:** Bambu Studio
and OrcaSlicer publish only `ubuntu24.04` **x86_64** AppImages at the pinned
versions in `tools.toml` -- no `linux/aarch64` build exists at all.
PrusaSlicer has no Linux binary whatsoever on its GitHub releases (Flatpak
is its only supported Linux channel, which is itself awkward inside Docker).
So a container that bundles any of today's three slicers is realistically
amd64-only; "multi-arch and contains a slicer" isn't simultaneously
achievable with this slicer set.

**If this is revisited:** the natural split is a multi-arch `printlab-core`
image (layer 1 only, no slicer -- covers CAD build, mesh analysis,
orientation search, evaluation, reporting on any arch) plus a separate
amd64-only `printlab-full` image that adds PrusaSlicer (the reference/CI
backend already used for golden reproducibility tests) -- bundling it would
let CI finally *run* those tests instead of skipping them for lack of an
installed slicer. Slic3r was evaluated and rejected as an alternative: it is
PrusaSlicer's unmaintained ancestor (last release 1.3.0, May 2018),
strictly worse and no more portable. A more promising path to a multi-arch
*full* image is a time-boxed spike on **CuraEngine**: unlike the other three
candidates, it's a standalone headless C++ console application (no GUI/Qt in
the engine itself, unlike Cura's frontend), which is architecturally the
right shape for containerizing and for going multi-arch if its build
publishes `linux/aarch64` -- at the cost of a lower-level CLI/config format
and a new G-code-flavor adapter (`printlab/slicing/base.py`'s
`SlicerBackend` abstraction exists to make exactly this kind of backend swap
cheap).
