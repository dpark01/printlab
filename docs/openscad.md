# OpenSCAD Backend

PrintLab's OpenSCAD backend compiles configured `.scad` source to CSG and a
reference STL. FreeCAD translates the CSG to BREP geometry, which PrintLab
accepts only when it contains one valid closed solid, uses no mesh or
placeholder fallback, and matches the OpenSCAD reference within the configured
surface, volume, and bounding-box tolerances.

## FreeCAD Compatibility

The pinned FreeCAD 1.1.1 CSG importer has two relevant reconstruction defects.
The bridge applies narrow BREP-only repairs before validation:

- A `linear_extrude()` dependency can remain null when `intersection()` is
  evaluated. The bridge recursively recomputes null dependency shapes before
  booleans, following the diagnosis in
  [FreeCAD #24790](https://github.com/FreeCAD/FreeCAD/issues/24790).
- `linear_extrude(union(...))` can import an overlapping 2D union as adjacent
  solid fragments. The bridge fuses imported BREP fragments before checking
  the one-solid contract. Genuinely disconnected bodies remain multiple solids
  and are rejected.

Both repairs remain subject to the same strict validity and independent
reference-STL comparison as every other OpenSCAD build. They never convert a
mesh into a nominal BREP.

If FreeCAD still reports `freecad_null_input_shape` from an intersection,
rewrite `intersection(A, B)` as `difference(A, difference(A, B))`. If it reports
`freecad_multiple_solids`, first verify that the design is one connected volume
and that joined bodies overlap by nonzero volume rather than only touching. For
the known 2D-profile defect, replacing a shared `linear_extrude(union(...))`
with separate `linear_extrude()` operations joined by a 3D `union()` can avoid
the faulty importer path.

OpenSCAD operations that make FreeCAD create a mesh or unsupported placeholder
remain intentionally rejected with `non_brep_fallback`. The bridge does not
weaken that policy to accept geometry that cannot support downstream STEP and
FEA workflows.
