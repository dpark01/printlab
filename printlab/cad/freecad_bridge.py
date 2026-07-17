"""Standalone FreeCADCmd script that converts OpenSCAD CSG to one STEP solid."""

from __future__ import annotations

import json
import os
import sys
import traceback


class BridgeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        hint: str | None = None,
        context: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.context = context or {}


def _write_metadata(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _recompute_shape_tree(obj) -> None:
    """Recompute null dependencies before the importer evaluates a boolean."""
    shape = getattr(obj, "Shape", None)
    if shape is None or not shape.isNull():
        return
    obj.recompute()
    if not obj.Shape.isNull():
        return
    for child in getattr(obj, "OutList", ()):
        _recompute_shape_tree(child)
    document = getattr(obj, "Document", None)
    if document is not None:
        document.recompute()


def main() -> int:
    csg_path = os.environ["PRINTLAB_CSG_PATH"]
    step_path = os.environ["PRINTLAB_STEP_PATH"]
    metadata_path = os.environ["PRINTLAB_BRIDGE_METADATA_PATH"]
    try:
        import FreeCAD
        import importCSG
        import Part

        preferences = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/OpenSCAD")
        preferences.SetInt("useMaxFN", 0)
        preferences.SetFloat("meshmaxlength", 0.1)
        preferences.SetInt("tempmeshmaxpoints", 5000)

        # FreeCAD 1.1.1's stock importer checks only the immediate object. An
        # extrusion can therefore remain null until its dependency is recomputed.
        # See https://github.com/FreeCAD/FreeCAD/issues/24790.
        importCSG.checkObjShape = _recompute_shape_tree
        document = importCSG.open(csg_path)
        document.recompute()
        fallback_objects = []
        for obj in document.Objects:
            proxy = getattr(obj, "Proxy", None)
            proxy_name = type(proxy).__name__ if proxy is not None else ""
            if proxy_name in {"CGALFeature", "OpenSCADPlaceholder"} or obj.TypeId.startswith("Mesh::"):
                fallback_objects.append({"name": obj.Name, "type": obj.TypeId, "proxy": proxy_name})

        root_shapes = []
        for obj in document.RootObjects:
            shape = getattr(obj, "Shape", None)
            if shape is not None and not shape.isNull() and shape.Volume > 0:
                root_shapes.append(shape)
        imported_solids = [solid for shape in root_shapes for solid in shape.Solids]
        if not imported_solids:
            raise BridgeError(
                "FreeCAD CSG import produced no solids",
                code="freecad_no_solids",
                context={"imported_solid_count": 0, "solid_count": 0},
            )

        # The stock importer can leave an extruded 2D union split into adjacent
        # BREP fragments. Fuse those fragments before enforcing the one-solid
        # contract; genuinely disconnected bodies remain multiple solids.
        fused_shape = imported_solids[0]
        for fragment in imported_solids[1:]:
            fused_shape = fused_shape.fuse(fragment)
        fused_shape = fused_shape.removeSplitter()
        solids = list(fused_shape.Solids)
        if len(solids) != 1:
            raise BridgeError(
                f"expected exactly one solid from CSG import, got {len(solids)} after fusion",
                code="freecad_multiple_solids",
                hint=(
                    "Ensure the intended part is one connected volume and that joined bodies "
                    "overlap by nonzero volume rather than only touching."
                ),
                context={
                    "imported_solid_count": len(imported_solids),
                    "solid_count": len(solids),
                },
            )
        solid = solids[0].removeSplitter()
        if not solid.isValid() or not solid.isClosed() or solid.Volume <= 0:
            raise RuntimeError("FreeCAD produced an invalid or open solid")

        output = document.addObject("Part::Feature", "PrintLabSolid")
        output.Shape = solid
        Part.export([output], step_path)
        if not os.path.isfile(step_path) or os.path.getsize(step_path) == 0:
            raise RuntimeError("FreeCAD did not produce a non-empty STEP file")
        _write_metadata(
            metadata_path,
            {
                "status": "ok",
                "fallback_objects": fallback_objects,
                "imported_solid_count": len(imported_solids),
                "solid_count": len(solids),
                "volume_mm3": solid.Volume,
                "face_count": len(solid.Faces),
            },
        )
        return 0
    except Exception as exc:
        trace = traceback.format_exc()
        metadata = {"status": "error", "error": str(exc), "traceback": trace}
        if isinstance(exc, BridgeError):
            metadata["error_code"] = exc.code
            metadata.update(exc.context)
            if exc.hint:
                metadata["hint"] = exc.hint
        elif "Null input shape" in str(exc):
            hint = "FreeCAD could not evaluate a CSG operation because one operand was null."
            if "p_intersection_action" in trace:
                hint += (
                    " If it contains an extruded shape, rewrite intersection(A, B) as "
                    "difference(A, difference(A, B))."
                )
            metadata.update(
                {
                    "error_code": "freecad_null_input_shape",
                    "hint": hint,
                }
            )
        _write_metadata(
            metadata_path,
            metadata,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
