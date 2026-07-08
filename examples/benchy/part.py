"""3DBenchy: the standard slicer torture-test hull, vendored rather than
built from primitives. Its sculpted organic surfaces (overhangs, bridges,
the chimney, curved gunwale) aren't a good fit for Shape-level parametric
construction the way `examples/bracket/part.py`'s L-bracket is -- and no
scripted/parametric recreation of the hull exists. As of its 10th
anniversary, CreativeTools released the official CAD source into the public
domain, so we vendor that directly instead.

Source: "3DBenchy by Daniel Noreee" STEP export, downloaded 2026-07-07 from
https://www.printables.com/model/1618564-original-3dbenchy-public-domain-cad-step-file
License: CC0 1.0 Universal (Creative Commons -- Public Domain).

There's no parametric geometry here to tune -- the only "edit" this file
supports is swapping or re-pulling the vendored STEP.
"""

from __future__ import annotations

from pathlib import Path

import cadquery as cq

STEP_PATH = Path(__file__).parent / "vendor" / "3DBenchy.step"


def build() -> cq.Workplane:
    return cq.importers.importStep(str(STEP_PATH))
