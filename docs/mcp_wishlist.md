# PrintLab MCP tools — wishlist from an external redesign session

## Where this comes from

This is a field report from a real session: fixing vanishing bow-side lettering
and a too-thin hull floor on a decorative canoe (`examples/canoe/part.py`,
shared elsewhere as `Canoe.py`), done **entirely through the `printlab` MCP
tools** from an agent working in a different project directory — no local
`printlab` git checkout in context at the start, no `.claude/skills/`
available, no `AGENTS.md` in view. Everything below was hit live, not
speculated.

The framing the user gave for this doc: *"every time in this session I found
myself reaching back into the codebase directly is a failure for the MCP
tool itself."* That's the organizing principle. Section counts below cite
exact files/lines in the current tree so a coding agent can act on this
without re-deriving it.

## The pattern behind most of these findings

`printlab`'s `AGENTS.md`, its two Claude Code skills
(`.claude/skills/printlab-iterate`, `.claude/skills/printlab-render`), and
several in-code comments already contain excellent, hard-won operating
guidance — how to interpret `provisional_score`, how `printlab_orient`
breaks ties, what "wall thickness" actually measures and why it isn't a true
minimum, that `output/` is fully disposable. **Almost none of it reaches an
MCP client.** It lives in:

- A markdown file (`AGENTS.md`) that only a session rooted in the `printlab`
  checkout will ever read.
- Two skills (`.claude/skills/*/SKILL.md`) that literally shell out via
  `Bash(uv run printlab*)` — they assume CLI + repo-root cwd, and are
  invisible to any MCP client, including Claude sessions working from an
  unrelated project directory (this session's exact situation).
- Python `#:`-style Sphinx comments on Pydantic fields (e.g.
  `printlab/schemas/evaluation.py:48-56`, `printlab/schemas/mesh.py:42-44`)
  — these render nicely for someone reading source, but **`#:` comments are
  not `Field(description=...)`, so they do not appear in the JSON schema
  FastMCP exposes to a client.** The caveat text exists; it just never
  crosses the MCP boundary.
- One-line MCP tool docstrings (`printlab_mcp/server.py`) that summarize the
  pipeline stage but drop every caveat, unit, default-semantics note, and
  cross-reference the fuller internal docstring had.

**The single highest-leverage fix across this whole list**: stop writing
load-bearing caveats as source comments or docstrings-of-things-MCP-doesn't-
expose, and instead put them where an MCP client actually reads from — the
tool's own docstring (`server.py`), and the response schema's field
`description=`s (which FastMCP does surface). Most individual items below
are instances of this one gap.

**Demonstrated, not hypothetical**: this session's own assistant cited
"provisional score 80 → 100" as a headline result before self-correcting.
`AGENTS.md` explicitly names this exact failure mode ("an agent that
hill-climbs this scalar is chasing artifacts of the penalty scheme") — but
that warning lives only in `AGENTS.md` and a source comment, not in
anything the MCP surface returned. The guardrail existed. It just wasn't
reachable.

---

## A. `printlab.toml` / project setup is undiscoverable from the MCP surface

**What happened**: pointing `printlab_check` at a plain design folder
(`Canoe/`, containing only `Canoe.py` + generated STL/gcode/PNG, no
`printlab.toml`) failed with:

```
missing printlab.toml in <path>
```

No hint of the schema, no pointer to an example, no tool to scaffold one.
Recovering required `find`-ing an existing `printlab.toml` under
`examples/canoe/` on disk, reading it, and reverse-engineering the schema by
also reading `printlab/pipeline.py:load_part_config` (`pipeline.py:88-110`)
to learn:

1. `module` can be any filename (`part.py` is convention, not a
   requirement) — nothing surfaces this; it's only visible by reading
   `part_py=example_dir / part["module"]`.
2. `[profiles]` paths are "resolved relative to the repository root" per the
   template's own comment — but that comment doesn't say *which* repo root.
   It's actually `Path.cwd()` **of the running MCP server process**
   (`pipeline.py:90`, defaulting when `repo_root` isn't passed), which for a
   `claude mcp add ... --directory /path/to/printlab` registration is fixed
   at server-launch time, **not** at the example directory's location.
   Confirming this required reading `~/.claude.json`'s MCP server
   registration to find the `--directory` flag. An agent operating on a
   design folder that isn't inside the `printlab` checkout has no way to
   discover this without filesystem spelunking.

**Wishlist**:

1. **A5 (P0)** — Rewrite the `printlab.toml` template's profile-path comment
   to name the actual mechanism: *"resolved relative to the printlab MCP
   server's working directory at launch — typically wherever `printlab` was
   installed via `uv --directory <path>`, not this file's location. Run
   `printlab_doctor` to confirm which backends that installation can see."*
2. **A1 (P0)** — When `load_part_config` raises for a missing
   `printlab.toml`, include a minimal valid example in the error message
   (or a doc URL) instead of just the missing path. Cheap, high value — this
   was the very first wall hit in the session.
3. **A2 (P1)** — Add a `printlab_init(example_dir: str, module: str = "part.py") -> str`
   MCP tool that scaffolds a `printlab.toml` (with sane default
   printer/material/process profiles) pointing at an existing CAD module in
   that directory. Removes the need to hand-copy-and-edit another example's
   toml.
4. **A3 (P1)** — Surface the resolved `module` path in `printlab_check`'s
   returned artifact (or a new lightweight `printlab_describe(example_dir)`
   tool) so an agent can confirm "this is building `Canoe.py`'s `build()`"
   without reading the toml by hand.
5. **A4 (P2)** — `printlab_doctor` currently reports only backend
   versions. Consider it also reporting the resolved `repo_root` it will use
   for profile resolution — the one piece of "hidden" global state every
   `example_dir` call depends on.

---

## B. `printlab_render` doesn't expose knobs the pipeline already has, and has none for the recurring "small feature on a big part" case

**Current MCP signature** (`printlab_mcp/server.py:64-72`,
`printlab_mcp/tools.py:51-58`):

```python
def printlab_render(example_dir: str, views: list[str] | None = None, backend: str = "check") -> ToolResult
```

Docstring: `"Render part.stl to PNG(s); returns the RenderReport plus the
images inline."` — 13 words, no mention of valid `views` values or their
semantics.

### B1 (P0) — Elevation/azimuth already exist one layer down; the MCP tool drops them

The CLI already supports an arbitrary camera angle:
`printlab/cli/main.py:39-40` (`--elevation`, `--azimuth` options) and
`:104-124` (constructs `CameraView("custom", elevation, azimuth)` when both
are given). `pipeline.stage_render`'s `views` parameter is already typed as
`Sequence[str | CameraView]` (`pipeline.py:186`) — it *accepts* a
`CameraView` object today. The MCP wrapper's `views: list[str] | None`
signature simply never constructs one. This is a pure parity gap, not a
missing capability — cheapest fix on this whole list:

```python
def printlab_render(
    example_dir: str,
    views: list[str] | None = None,
    backend: str = "check",
    elevation: float | None = None,
    azimuth: float | None = None,
) -> RenderReport:
    if elevation is not None and azimuth is not None:
        views = [CameraView("custom", elevation, azimuth)]
    ...
```

Mirror the CLI's existing `elevation is not None and azimuth is not None`
branch (`cli/main.py:123-124`) exactly.

### B2 (P0) — No zoom / region-of-interest. This blocked visual verification entirely this session.

`printlab/rendering/mpl.py`'s own module docstring is explicit: *"no free
'camera distance' knob... Framing is derived entirely from mesh.bounds."*
`_fit_axes` (`mpl.py:55-66`) always frames the **entire mesh's bounding
box**. For this session's actual part — 2mm-tall lettering engraved into a
75mm-long hull — every preset and every custom angle rendered the feature
as a few dozen illegible pixels. The workaround was writing a standalone
Python script reimplementing the CAD module's own tangent-plane math to
verify the fix numerically instead of visually — exactly the "don't
eyeball it" discipline `AGENTS.md` calls for, but only because the render
tool made eyeballing impossible, not because numeric verification was the
first choice.

**Ask**: an optional region-of-interest override to `_fit_axes`, e.g.:

```python
def printlab_render(..., focus_center: tuple[float,float,float] | None = None,
                     focus_radius: float | None = None) -> RenderReport: ...
```

that overrides `_fit_axes`'s mesh-bounds framing with a fixed window around
a point (in the part's native coordinate frame — the same frame the CAD
source's own constants are written in, e.g. `SIDE_TEXT_X`/`SIDE_TEXT_Z` in
this session's part). Even a coarse implementation (axis-aligned cube of
`2*focus_radius` centered on `focus_center`, clamped to the mesh bounds)
would have turned this session's multi-script numeric workaround into one
render call.

### B3 (P1) — Tiled multi-panel render (requested live during this session)

Separate from zoom: today, seeing a part from more than one angle costs one
tool round-trip (and one image) per view. Requested enhancement: an optional
**single composited image** with 3 axis-aligned orthographic views plus the
existing angled (iso) view, tiled 2×2 — the standard "three-view + iso"
engineering-drawing layout:

```
┌───────────┬───────────┐
│  top (xy) │ front(xz) │
├───────────┼───────────┤
│ right(yz) │    iso    │
└───────────┴───────────┘
```

All four camera angles already exist as named presets
(`printlab/rendering/mpl.py:43-51`: `top`, `front`, `right`, `iso`) — this
is a compositing feature, not new camera math. Proposed shape:

```python
def printlab_render(
    example_dir: str,
    views: list[str] | None = None,
    backend: str = "check",
    layout: Literal["separate", "grid"] = "separate",
    ...
) -> RenderReport: ...
```

`layout="grid"` renders `top`/`front`/`right`/`iso` (or whatever `views`
resolves to, up to 4) into one `Figure` with a 2×2 `add_subplot(2,2,i,
projection="3d")` grid instead of one `Figure` per view
(`printlab/rendering/mpl.py:69-93`'s `render_mesh_png` is the function to
generalize into a multi-axes version; `render_views` at `:97+` is the
per-file loop to branch from). **Resolution caveat, worth stating
explicitly in the implementation**: if each panel keeps the current default
800×600, the composited canvas must scale to ~1600×1200 (not shrink each
panel to fit inside 800×600) — this feature exists specifically to help
read small detail, so tiling should not compound the B2 zoom problem by
also shrinking each panel.

Open question for whoever implements this (flagged, not resolved here):
should `layout="grid"` become the **default** render mode (replacing
today's default 3-separate-image `DEFAULT_VIEWS = ("iso","front","top")`,
`mpl.py:52`)? That's a call for whoever owns the tool's existing callers —
listed here as a genuine trade-off, not a recommendation either way.

### B4 (P1) — View names aren't documented, and two of them are counter-intuitive

`views` accepts `"iso"|"front"|"back"|"left"|"right"|"top"|"bottom"`
(`mpl.py:43-51`) — none of this enumeration, nor what each means
geometrically, appears in the MCP tool's docstring or schema. This cost a
wasted tool call this session: `"left"`/`"right"` were assumed to be side
profiles (like a ship's port/starboard elevation) but are actually **end-on
views looking down the part's long axis** (`azimuth=180/0` with
`elevation=0`, i.e. bow/stern silhouettes) — the actual lengthwise side
profile is `"front"`/`"back"` (`azimuth=-90/90`). Minimal fix: state the
valid values and what plane each looks down, directly in the docstring, e.g.
*"views: preset camera angles — iso (3/4 angled), front/back (look along Y,
side profile), left/right (look along X, end-on), top/bottom (look along
Z)."*

### B5 (P2) — `printlab_render`'s docstring implies a pre-built `part.stl` is required

*"Render **part.stl** to PNG(s)"* — in practice it calls `ensure_built`
(`tools.py:22-30, 55`) and builds automatically if needed. Minor, but worth
tightening so an agent doesn't assume it must call `printlab_check` first.

---

## C. Docstrings that reference context an MCP client can't reach

Every item here is the same root cause: real, correct, well-written prose
exists — just one hop past what an MCP client can see.

### C1 (P0) — `provisional_score`'s calibration warning never reaches the MCP schema

`printlab/schemas/evaluation.py:2-22` (module docstring) and `:48-56`
(per-field `#:` comments) contain exactly the caveat an agent needs:
*"UNCALIBRATED... must not be optimized... hill-climbing `provisional_score`
is off-limits."* `AGENTS.md:29-37` repeats it. **None of this is a
`Field(description=...)`** — `#:` comments don't serialize into
`model_json_schema()`, which is what FastMCP uses to build the client-visible
output schema. An MCP client sees only the raw values:
`{"provisional_score": 100, "score_calibrated": false}`, with zero indication
that the first number is meaningless without the second. This session's own
transcript is the proof: the 80→100 jump got reported to the user as
headline evidence of the fix's quality before self-correcting.

**Fix**: convert the `#:` comments on `provisional_score` and
`score_calibrated` (`evaluation.py:48-56`) into actual `Field(description=...)`,
carrying the "do not optimize / uncalibrated" language verbatim. This is a
two-field change that fixes the single most consequential documentation gap
found this session.

### C2 (P0) — `min_wall_thickness_mm`'s "not a true minimum" caveat is comment-only, and the check message points at an unreachable doc

`printlab/mesh/wall_thickness.py:1-27`'s module docstring is genuinely
excellent — it explains *why* the value is a 5th-percentile
(`DEFAULT_PERCENTILE = 5.0`, `wall_thickness.py:51`) rather than a strict
minimum, with a worked example (a plain 6mm-radius cylinder misreporting
~4.6mm instead of ~12mm from edge artifacts). None of this reaches
`MeshReport.min_wall_thickness_mm` (`printlab/schemas/mesh.py:42-45`, again
a `#`-comment, not a `Field(description=...)`), and the printability check's
own message literally says:

> "Estimated wall thickness 0.24mm is below Bambu Lab A1's 0.4mm minimum
> feature size (approximate — **see printlab.mesh.wall_thickness
> limitations**)."

`printlab.mesh.wall_thickness` is a Python module path, not a citation an
MCP client (or any agent without the repo checked out) can resolve. Fix:
move the percentile-vs-minimum explanation into the `Field(description=...)`
for `min_wall_thickness_mm`, and change the check message to state the
actual mechanism inline ("5th-percentile of per-face ray-cast readings, not
a strict minimum — can overestimate true worst-case thickness near sharp
edges") instead of pointing at a module.

### C3 (P1) — `printlab_orient`'s tie-break criteria are undocumented at the tool layer

`AGENTS.md:47-53` and `printlab/mesh/orientation.py:21` both state the exact
rule: *minimize overhang area, then maximize wall thickness, then minimize
unsupported span* — a deliberate, explicit chain, not a weighted score.
`printlab_orient`'s MCP docstring says only *"Try axis-aligned rotations of
part.stl and recommend one (mesh-metrics only)."* The report does include a
`selection_reason` field (per `orientation.py:125-135`) which is good — but
the tie-break *rule itself* should also be in the tool docstring so an agent
can decide whether to trust a recommendation without needing to inspect that
field's prose after the fact.

### C4 (P1) — CAD-source docstrings that reference `AGENTS.md` are dead references outside the printlab checkout

This session's `Canoe.py` (an example CAD module distributed outside the
`printlab` repo, in a family-shared design folder) opens with: *"This is the
only file in this example an agent (or a human) should edit — `build()` is
CAD source; everything else in an output/ directory is a generated artifact
(**see AGENTS.md**)."* There is no `AGENTS.md` anywhere near that file — it
only exists at the `printlab` repo root. Whatever example-authoring template
generates this docstring boilerplate (or whichever human/agent wrote it by
hand for `examples/canoe/part.py`) should inline the one or two load-bearing
sentences from `AGENTS.md`'s "edit only CAD source" rule directly, rather
than citing a file that only travels with the `printlab` checkout itself.
More generally: **any prose intended to guide an agent editing a CAD module
should be self-contained in that module's own docstring** — it will very
often be read (and, as here, edited) from outside the `printlab` project
entirely.

### C5 (P2) — The two `.claude/skills/` encode real operating discipline that MCP-only clients never get

`.claude/skills/printlab-iterate/SKILL.md` and `printlab-render/SKILL.md`
are well-written distillations of `AGENTS.md` — but both are
`Bash(uv run printlab*)`-based and assume a `printlab` repo-rooted cwd. Any
MCP client working from a different project directory (this session, in
full) has no access to either, and gets none of: "read the JSON, not the
Markdown," "orient before eyeballing," "rerun after every edit," "never
optimize `provisional_score`," etc., except by rediscovering it independently.
Consider whether the *procedural* content of these skills (not the
CLI-specific commands) belongs in the FastMCP server's `instructions=`
string (`server.py:24-32`, currently three sentences) instead of — or in
addition to — the skills. That `instructions` string is the one piece of
guidance every MCP client actually receives regardless of cwd or skill
availability, which makes it the highest-leverage place to put anything from
`AGENTS.md` that should generalize.

---

## D. Diagnostics that stop one step short of "where"

### D1 (P1) — `min_wall_thickness_mm` is a bare scalar; the machinery to localize it already exists and is thrown away

`estimate_min_wall_thickness_mm` (`printlab/mesh/wall_thickness.py:96+`)
internally builds `per_face_hits: dict[int, list[float]]` — a per-face
thickness reading, keyed by face index, i.e. it already knows exactly which
faces are thin. The function reduces this to one float and returns. This
session had to hand-derive *where* the thin region was (a keel floor at a
specific `z`, worked out algebraically from the CAD module's own constants)
purely because the tool reported "0.24mm" with no location. **Ask**: extend
`MeshReport` with an optional `min_wall_thickness_location: tuple[float,
float, float] | None` (the centroid of the lowest-percentile face, already
computed and discarded at `wall_thickness.py`'s `centroids = mesh.triangles_center`),
or a small `thin_regions: list[{location, thickness_mm}]` for the bottom-N
percentile faces. This is a genuinely small change (the data already exists
in-memory) with outsized value for exactly the workflow `AGENTS.md`
prescribes — "propose CAD-source edits from the returned artifacts" is much
easier when the artifact says *where*.

### D2 (P2) — `printlab_fea`'s `[fea]` requirement isn't discoverable until you hit the error

`printlab_fea` requires a target's `printlab.toml` to have an `[fea]`
table, or it raises `f"{example_dir} has no [fea] load case in
printlab.toml"` (`tools.py:65-66`). Neither the MCP docstring
(`server.py:76-79`) nor any other tool response indicates this ahead of
time, nor what fields the `[fea]` table needs. Fix: state the requirement
and minimal schema in the docstring, and/or have `printlab_check`'s
response note whether `[fea]` is configured for that part (cheap to add,
saves a guaranteed-to-fail round trip for any part without one — which, per
`AGENTS.md:71-72`, is every example except `examples/hook` today).

---

## E. Output/workspace hygiene has no MCP-level control

**What happened**: running `printlab_check`/`printlab_render`/`printlab_all`
against a shared, non-repo design folder (a family Google Drive folder, not
a git checkout) left `output/check/`, `output/bambu/`, and a stray
`__pycache__/` sitting directly in that folder — none of which fit that
folder's existing flat convention (source + STL + gcode + photo). This
required a manual, user-adjudicated decision afterward about what to keep
vs. delete.

This is expected/correct behavior for `printlab`'s own repo layout
(`AGENTS.md:10-13` explicitly documents `output/` as disposable, and
`prepare_output_dir(..., clean=True)` in `run_all`/`run_check`,
`pipeline.py:301,378`, wipes it every run by design) — the gap is that
nothing about this is surfaced when `example_dir` is *not* inside a
`printlab`-managed tree, where a caller has no prior expectation that
calling a "check" tool will create and manage a persistent subdirectory as
a side effect.

**Wishlist**:

1. **E1 (P1)** — Add an optional `output_dir: str | None` override to
   `printlab_check`/`printlab_render`/`printlab_all`/`printlab_orient`/
   `printlab_fea` (the pipeline functions already accept this —
   `run_all`/`run_check` both take `output_dir: Path | None = None`,
   `pipeline.py:297,366` — it's only the MCP wrappers in `tools.py` that
   don't forward it). Lets an agent redirect build/report artifacts to a
   scratch location instead of always writing into `example_dir/output/`.
2. **E2 (P2)** — Have `printlab_check`'s (or `printlab_doctor`'s) response
   note explicitly that `output/<backend>/` is fully disposable and will be
   wiped clean (`clean=True`) on the next run against the same backend —
   the single most useful line from `AGENTS.md:10-13`, currently invisible
   outside it.
3. **E3 (P2)** — Consider suppressing `__pycache__/` generation when
   importing a CAD module for build (e.g. `sys.dont_write_bytecode = True`
   around the import in `stage_build`, or set `PYTHONDONTWRITEBYTECODE`) —
   pure build byproduct, never useful to a caller, currently left behind
   unconditionally.

---

## F. Small consistency nits worth cleaning up while in this code

1. **F1 (P2)** — Default `backend` value is inconsistent across tools:
   `printlab_render`/`printlab_orient`/`printlab_fea` default to
   `"check"`; `printlab_all` defaults to `"prusaslicer"`
   (`server.py:44-87`). `"check"` isn't a real slicer backend — it's a
   sentinel meaning "skip slicing." Worth either renaming the parameter's
   semantics to make that explicit (e.g. a `slice: bool = False` flag
   alongside a real `backend` name) or at minimum stating in every tool's
   docstring that `"check"` is a no-slicer sentinel, not a backend choice.
2. **F2 (P2)** — `docs/mcp.md`'s tool table already documents current
   signatures reasonably well but is itself missing the CLI's
   `--elevation`/`--azimuth` parity gap (B1) and the `[fea]`-table
   requirement's discoverability gap (D2) — worth a pass once B1/D2 land, so
   the doc and the tool agree again.

---

## G. The "sanctioned iterate loop" has no MCP form

`AGENTS.md:54-61` names `scripts/optimize_loop.py` as *"the sanctioned agent
loop... not an ad hoc edit/rerun cycle"* — a `propose_edit(source,
last_result) -> str | None` callback around `run_check`/`run_all` with a
documented stopping rule (no ERROR-level check remains, target metric
stops improving for `patience` iterations, or `max_iters` reached). This
script is CLI/repo-only; no MCP tool wraps it. This session's actual
workflow — hand-edit `Canoe.py`, call `printlab_check`, read the result,
edit again — is precisely the "ad hoc edit/rerun cycle" `AGENTS.md` warns
against, and was the only option available over MCP. If the sanctioned loop
is meaningfully better (bounded iteration, explicit stopping rule, automatic
restore-on-failure), it should be reachable the same way everything else in
this list should be: as a tool, not a script that only exists for CLI
callers inside the repo.

---

## Priority summary

| ID | Item | Priority |
|----|------|----------|
| A1 | Missing-toml error should show a minimal example | P0 |
| A5 | Fix the profile-path-resolution comment in the toml template | P0 |
| B1 | Forward elevation/azimuth through `printlab_render` (pipeline already supports it) | P0 |
| B2 | Region-of-interest / zoom for render (blocked visual verification this session) | P0 |
| C1 | `provisional_score` caveat into `Field(description=...)` | P0 |
| C2 | `min_wall_thickness_mm` caveat into `Field(description=...)`; fix dangling module-path citation | P0 |
| A2 | `printlab_init` scaffolding tool | P1 |
| A3 | Surface resolved module/config in a describe-style response | P1 |
| B3 | Tiled 2×2 multi-view render | P1 |
| B4 | Document view names/semantics in docstring | P1 |
| C3 | Surface `printlab_orient`'s tie-break rule in its docstring | P1 |
| C4 | Fix dangling `AGENTS.md` reference in example CAD docstrings | P1 |
| D1 | Localize `min_wall_thickness_mm` (data already computed, just discarded) | P1 |
| E1 | `output_dir` override param on all `example_dir` tools | P1 |
| A4 | `printlab_doctor` reports resolved `repo_root` | P2 |
| B5 | Fix stale "requires part.stl" docstring wording | P2 |
| C5 | Fold skill-level procedural guidance into `mcp.instructions` | P2 |
| D2 | Surface `[fea]` requirement ahead of the error | P2 |
| E2 | State `output/` disposability in tool responses | P2 |
| E3 | Suppress `__pycache__` generation during build | P2 |
| F1 | Clarify `"check"` as a non-backend sentinel | P2 |
| F2 | Sync `docs/mcp.md` once B1/D2 land | P2 |
| G  | Expose the sanctioned optimize-loop as an MCP tool | P2 |

---

## Appendix: chronological log of "reach-ins" this session

For traceability — every point in this session where the assistant left the
MCP tool surface and went to the `printlab` source/config/filesystem
directly, in order:

1. `printlab_check` on the design folder failed (`missing printlab.toml`) →
   searched the filesystem for an existing `printlab.toml` to copy from.
2. Read `printlab/pipeline.py` to learn the `module` key isn't required to
   be named `part.py`.
3. Read `printlab/pipeline.py`'s `load_part_config` to learn `repo_root`
   defaults to the server process's `cwd`, not the example directory.
4. Read `~/.claude.json` to find the MCP server's `--directory` flag and
   confirm what `cwd` actually resolves to.
5. Asked for (and copied over) an existing stored `printability_report.json`
   from `examples/canoe/output/bambu/` to confirm the pre-existing thin-wall
   defect had, in fact, already been flagged by a prior run — information
   nowhere surfaced by the live MCP tools on the un-toml'd folder.
6. Read `printlab/rendering/mpl.py` to learn the actual meaning of the
   `"left"`/`"right"` view presets after a render came back as an
   unexpected end-on silhouette.
7. Read `printlab/rendering/mpl.py`'s module docstring to confirm there is
   no camera-distance/zoom control at all, before giving up on visual
   verification of a small engraved feature and writing a standalone
   Python script to verify it numerically instead.
8. Read `AGENTS.md`, `docs/mcp.md`, and both `.claude/skills/*/SKILL.md` to
   understand what operating discipline exists in the project but wasn't
   reaching this session through the MCP tools.
9. Read `printlab/cli/main.py` to discover `--elevation`/`--azimuth` exist
   at the CLI layer with no MCP equivalent.
10. Read `printlab/mesh/wall_thickness.py`, `printlab/schemas/mesh.py`, and
    `printlab/schemas/evaluation.py` to confirm the percentile-not-minimum
    and uncalibrated-score caveats exist only as source comments, not in
    any MCP-visible schema.

Eleven distinct reach-ins for one design-fix session. None of them were
exotic — every one was "what does this parameter actually accept" or "why
did this behave unexpectedly," which is exactly what tool docstrings and
response schemas exist to answer.
