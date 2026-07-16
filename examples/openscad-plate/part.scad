// Parametric two-hole mounting plate used to exercise the OpenSCAD backend.
// All dimensions are in millimeters.
PLATE_WIDTH = 36;
PLATE_DEPTH = 24;
PLATE_THICKNESS = 4;
HOLE_DIAMETER = 5;
HOLE_SPACING = 22;

$fn = 64;

difference() {
    translate([-PLATE_WIDTH / 2, -PLATE_DEPTH / 2, 0])
        cube([PLATE_WIDTH, PLATE_DEPTH, PLATE_THICKNESS]);

    for (x = [-HOLE_SPACING / 2, HOLE_SPACING / 2])
        translate([x, 0, -1])
            cylinder(h = PLATE_THICKNESS + 2, d = HOLE_DIAMETER);
}
