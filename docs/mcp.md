# MCP server & Claude Code skills

`printlab_mcp` exposes PrintLab's pipeline over the [Model Context
Protocol](https://modelcontextprotocol.io) so an MCP-aware agent (Claude Code,
Claude Desktop, or any MCP client) can build, check, orient, and render parts
as tools.

**It is a strictly optional adapter.** `printlab_mcp` depends on `printlab`;
`printlab` never depends on `printlab_mcp` (or on `fastmcp`, or on any agent
framework). The core stays LLM-agnostic — the pipeline owns the truth, the LLM
owns proposals (see [`AGENTS.md`](../AGENTS.md)). Only two files exist:

- `printlab_mcp/tools.py` — plain functions wrapping `printlab.pipeline`,
  importing *only* `printlab` (no `fastmcp`), so they're unit-testable with no
  MCP install.
- `printlab_mcp/server.py` — the one module that imports `fastmcp`; it wraps
  each `tools.py` function as an `@mcp.tool` and translates PrintLab's own
  exceptions into clean MCP errors.

## Install

`fastmcp` lives behind the optional `mcp` extra, so a plain `uv sync` never
pulls it in:

```bash
uv sync --extra mcp
```

## Run for Claude Code (stdio)

The server speaks stdio by default. `uv run` needs its working directory to be
the repo root to find `pyproject.toml`, so pin it explicitly rather than
relying on wherever Claude Code happens to be launched from. Register it from
the repo root:

```bash
claude mcp add printlab --scope user -- uv --directory $(pwd) run printlab-mcp
```

or commit a `.mcp.json` at the repo root so the whole team picks it up:

```json
{
  "mcpServers": {
    "printlab": {
      "command": "uv",
      "args": ["run", "printlab-mcp"]
    }
  }
}
```

Unlike the personal registration above, this can't pin an absolute path —
`.mcp.json` is shared, and each teammate's checkout lives somewhere different.
It works only as long as Claude Code is launched with the repo root as its
working directory. `CLAUDE_PROJECT_DIR` doesn't rescue this: Claude Code sets
it in the *spawned server's* environment, not its own, so `${CLAUDE_PROJECT_DIR}`
in a project-scoped `.mcp.json`'s `command`/`args` needs a `:-.` fallback that
just resolves back to cwd — no improvement over the bare `uv run` above.

(`uv run` resolves the `printlab-mcp` console script defined in
`pyproject.toml`. Run `claude mcp list` to confirm it registered.)

## Run over HTTP (remote)

For a remote client, serve over streamable HTTP instead of stdio:

```bash
uv run printlab-mcp --http --host 0.0.0.0 --port 8000
```

## Tools

Each `example_dir`-taking tool operates on a path to an `examples/<name>/`
directory containing `printlab.toml`, and returns the corresponding PrintLab
artifact as structured content. `printlab_check`, `printlab_orient`, and
`printlab_render` need no slicer; `printlab_all` does (query `printlab_doctor`
first). `backend` defaults to `"check"` almost everywhere -- a no-slicer
*sentinel* (skip slicing entirely), not a real backend name; the real
choices are `"prusaslicer"`/`"bambu"`. Every `example_dir` tool also accepts
an optional `output_dir` to redirect artifacts away from the default
`<example_dir>/output/<backend>/` (itself fully disposable -- wiped and
regenerated on every run against that backend).

| Tool                | Signature                                                                                                                                                                                                                     | Returns                                | Slicer? |
|---------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------|---------|
| `printlab_check`    | `printlab_check(example_dir: str, output_dir: str \| None = None)`                                                                                                                                                             | `PrintabilityReport`                    | no      |
| `printlab_all`      | `printlab_all(example_dir: str, backend: str = "prusaslicer", output_dir: str \| None = None)`                                                                                                                                 | `PrintabilityReport`                    | yes     |
| `printlab_orient`   | `printlab_orient(example_dir: str, backend: str = "check", output_dir: str \| None = None)`                                                                                                                                    | `OrientationSearchReport`               | no      |
| `printlab_render`   | `printlab_render(example_dir: str, views: list[str] \| None = None, backend: str = "check", elevation: float \| None = None, azimuth: float \| None = None, layout: "separate"\|"grid" = "separate", focus_center: tuple \| None = None, focus_radius: float \| None = None, output_dir: str \| None = None)` | `RenderReport` + PNG images             | no      |
| `printlab_fea`      | `printlab_fea(example_dir: str, backend: str = "check", output_dir: str \| None = None)`                                                                                                                                       | `FEAReport`                             | no      |
| `printlab_doctor`   | `printlab_doctor()`                                                                                                                                                                                                             | per-backend version dict + `repo_root`  | no      |
| `printlab_init`     | `printlab_init(example_dir: str, module: str = "part.py")`                                                                                                                                                                     | path to scaffolded toml (`str`)         | no      |
| `printlab_describe` | `printlab_describe(example_dir: str)`                                                                                                                                                                                          | resolved-config dict                    | no      |

`printlab_render`'s `views` presets: `iso` (3/4 angled), `front`/`back` (look
along Y, lengthwise side profile), `left`/`right` (look along X, **end-on**
silhouettes -- not a side profile despite the name), `top`/`bottom` (look
along Z). Pass both `elevation`/`azimuth` for one custom angle instead of
presets. `layout="grid"` composites up to 4 views into one 2x2 PNG at double
the per-panel resolution, instead of one file per view. `focus_center` +
`focus_radius` zoom into a fixed cube around a point (part-native
coordinates) instead of framing the whole mesh -- for a small feature on an
otherwise large part. `printlab_render` returns the `RenderReport` as
structured content *and* the rendered PNGs as inline image blocks (via
`fastmcp.utilities.types.Image`), so a vision-capable client can see the part
directly; the report's `views[].output_path` fields also point at the files
on disk (all views share one file when `layout="grid"`).

`printlab_fea` requires the `fea` extra (`uv sync --extra fea`, which installs
`gmsh`) and a working `ccx` (CalculiX) on PATH -- see
[`docs/fea.md`](fea.md). It needs an `[fea]` load case in the target
example's `printlab.toml` (`load_point_mm`/`load_force_n`/
`load_region_radius_mm`, optional `fixed_region`); only `examples/hook` has
one today. Call `printlab_describe` first to check `fea_configured` and
avoid a guaranteed-fail round trip. Results are a crude single-run linear
analysis on placeholder material constants, not certification-grade -- see
`printlab.schemas.fea` and `docs/fea.md`.

`printlab_init` scaffolds a `printlab.toml` for an existing CAD module
(default `part.py`) with default printer/material/process profiles; it
refuses to overwrite an existing toml or to scaffold one pointing at a module
that doesn't exist yet. `printlab_describe` resolves a `printlab.toml`
without building anything -- the CAD module/function, profile paths, the
`repo_root` they resolve against, and whether `[fea]` is configured -- useful
for confirming what a target directory will build, or before hand-writing a
toml at all (missing-toml errors from every other tool also now include a
minimal valid example inline).

## Skills

Two Claude Code skills under `.claude/skills/` drive these capabilities with
the deterministic-pipeline discipline from `AGENTS.md`:

- **`printlab-iterate`** — evaluate and iteratively improve a part: run the
  pipeline, read the JSON artifacts (not the Markdown), propose CAD-source
  edits to `part.py` only, rerun, and compare metrics numerically. Never
  bypasses a FAIL by loosening thresholds; never optimizes the uncalibrated
  `provisional_score`.
- **`printlab-render`** — render a part to PNGs from standard or custom camera
  angles and describe what it sees.
