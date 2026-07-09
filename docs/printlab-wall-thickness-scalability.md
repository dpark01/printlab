# Wall-thickness estimator: scalability problem and proposed fixes

Context for whoever picks this up: this came out of building `Canoe_10x`, a
10-up print-bed plate of an existing part (`Canoe-100mm`, ~14.4k mesh faces),
laid out as 10 disjoint solids in one STL for a single-plate print. Running
`printlab_check`/`printlab_all` against that plate was dramatically slower
and more memory-hungry than the single-part case, to the point of needing to
be aborted. The relevant code is `printlab/mesh/wall_thickness.py`
(`estimate_min_wall_thickness`).

## The problem

`estimate_min_wall_thickness` estimates local wall thickness via a
shape-diameter-function approximation: for every face in the mesh, cast a
small cone of rays (1 + `DEFAULT_CONE_SIDE_RAYS` = 7 rays) inward from the
face centroid and take the median hit distance; the reported thickness is
the 5th percentile of all per-face medians (not the strict minimum — see the
module's own docstring for why).

Two properties of the current implementation compound badly as a design
grows from "one part" to "many parts on one plate":

1. **Cost scales with total face count across the whole mesh, not per part.**
   All rays are cast against a single `trimesh.ray.intersects_location` BVH
   built over *every* face in the STL, regardless of which disjoint solid a
   ray's origin face belongs to. The module's own docstring documents
   measuring **16-19GB peak RSS** casting all ~101k rays for a *single*
   14.4k-face hull at once, before a batching mitigation (2,000 rays/batch)
   brought that down to ~3.3GB peak for that one part. A 10-part plate has
   ~10x the faces and ~10x the rays, and — because the BVH the rays are
   cast against is also ~10x bigger — likely worse than linear scaling in
   both time and per-ray memory (more AABB-overlapping candidate triangles
   per query as the tree grows), not just a clean 10x.

2. **A ray can hit the wrong solid.** Because all rays are cast against the
   whole-mesh BVH rather than a ray's own originating shell, a ray searching
   "inward for the opposite wall" can leak across the gap between two
   *disjoint but nearby* solids and register a hit on a neighboring part
   instead of its own opposite wall. This is silent — no error, just a wrong
   thickness reading — and it gets *more* likely, not less, on exactly the
   kind of design that benefits most from wall-thickness checking: densely
   packed multi-part plates with small intentional clearances between parts
   (e.g. the staggered/interleaved canoe layout, where hulls are deliberately
   placed a few mm apart).

So today: multi-part plates are both much slower/heavier *and* have a latent
correctness bug that gets worse the more tightly parts are packed.

## Proposed fixes, in priority order

### 1. (Highest priority) Split the mesh into connected components before ray-casting

Segment the input mesh into its connected components (`trimesh.Trimesh` /
`mesh.split()` does this directly) and run the existing per-face ray-casting
independently *within* each component — i.e. each shell's rays only ever
query a BVH built from that shell's own faces, never the other shells'.
Aggregate the per-face medians across all components before taking the
final percentile (or take the fix a step further and report per-shell
percentiles too, see "nice to have" below).

This is both the performance fix and the correctness fix in one change:
- BVH size per query drops back to "one part's worth of faces," independent
  of how many other parts are on the plate — cost becomes ~linear in total
  face count again instead of super-linear, and each shell's cost is
  identical to analyzing that shell alone.
- Rays can no longer leak onto a neighboring solid, since the geometry they
  can possibly hit is restricted to their own shell.
- It's embarrassingly parallel across shells (independent problems), which
  isn't in scope for a first pass but is a natural follow-up.

This should be the first change made — it's a correctness fix that happens
to also be the biggest scalability fix, and the other proposals below are
either smaller in isolation or specifically valuable *in combination* with
this one.

### 2. (High priority) Bound total ray count via a capped, stratified sample

Independent of per-shell splitting: today the number of faces sampled (and
therefore rays cast) scales with total mesh size, with no ceiling. Since the
reported value is already a 5th-percentile statistic rather than an exact
minimum, it doesn't require exhaustively sampling every face to be
statistically sound — a size-capped sample (e.g. area-weighted / stratified,
up to some fixed budget like 20,000-50,000 faces) would keep cost bounded
and roughly constant regardless of how large or how many-parted the design
is, while still giving a solid percentile estimate.

This is the more general fix of the two: it helps any single very-high-poly
part (no repeated geometry required to benefit), not just multi-part plates,
and it turns "cost scales with design size" into "cost has a fixed ceiling,"
which is the property actually wanted here. It doesn't by itself fix the
cross-shell ray-leak bug, though — recommend pairing it with fix #1, not
using it as a substitute.

Open question for implementation: how to pick the sample so the percentile
estimate stays defensible (e.g. area-weighted sampling so large flat faces
aren't over- or under-represented relative to many small faces covering the
same physical area — this matters a lot here since text-carved surfaces
produce lots of small triangles that could otherwise dominate a naive
per-face-uniform sample).

### 3. (Nice to have, lower confidence on payoff) Dedupe congruent shells

For plates made of N repeated copies of the same part (like `Canoe_10x`),
once shells are already being split out (fix #1), it's cheap to fingerprint
each shell (e.g. hash of pose-normalized vertex/face data, or a simpler
invariant like sorted edge-length/face-area histograms) and skip re-running
ray-casting on any shell congruent to one already analyzed, broadcasting
that shell's result to its duplicates instead. For a 10-up plate of
identical parts, this turns an O(N × per-part cost) problem into
O(distinct-shapes × per-part cost) — for `Canoe_10x` specifically, 10x → 1x.

Flagging this as genuinely optional: it's a large win *specifically* for
batch/array plates of identical or near-identical parts, and a no-op for
plates of N distinct, non-repeating parts (which may be just as common a
use case, if not more so — assorted multi-part prints, not just N-up
plates). Worth doing if it falls out cheaply once shells are already being
split and hashed for other reasons, but I wouldn't block on it or spend
much dedicated effort here unless it turns out to be nearly free.

### 4. (Lead to check, not a recommendation) Accelerated ray-mesh backend

The wall-thickness module's own comments indicate it's using trimesh's
non-embree (pure rtree) `RayMeshIntersector`. trimesh has historically
supported an optional `pyembree`-accelerated backend that's substantially
faster for ray-mesh intersection at scale. Worth checking whether a
maintained accelerated backend (pyembree or a modern equivalent) is
actually installable/compatible with the current trimesh/Python version in
this project before investing here — if it is, it's a roughly-free
multiplier stacked on top of fixes #1 and #2, not a replacement for either
(it speeds up each ray query; it doesn't fix the BVH-scope or unbounded-
ray-count problems on its own).

## Suggested order of work

1. Split-by-connected-component (fix #1) — correctness fix + biggest
   scalability win, do this first.
2. Ray-count cap via stratified sampling (fix #2) — pair with #1, gives a
   hard ceiling on cost regardless of design size.
3. Investigate accelerated backend availability (fix #4) — cheap to check,
   stack on top if viable.
4. Congruent-shell dedup (fix #3) — only if it falls out easily once shells
   are already segmented; skip otherwise.

## Reference numbers

- Single canoe hull (`Canoe-100mm`): ~14.4k faces, ~101k rays (7 rays/face)
  unbatched, measured at 16-19GB peak RSS; batched to 2,000 rays/batch,
  ~3.3GB peak RSS for a full `run_check`.
- `Canoe_10x`: 10 copies of that same hull as disjoint solids in one STL —
  ~10x the faces and rays of the single-part case, observed to be slow/
  memory-heavy enough to need aborting during `printlab_check`.
