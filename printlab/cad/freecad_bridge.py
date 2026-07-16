"""Standalone FreeCADCmd script that converts OpenSCAD CSG to one STEP solid."""

from __future__ import annotations

import json
import os
import sys
import traceback


def _write_metadata(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


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
        solids = [solid for shape in root_shapes for solid in shape.Solids]
        if len(solids) != 1:
            raise RuntimeError(f"expected exactly one solid from CSG import, got {len(solids)}")
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
                "solid_count": len(solids),
                "volume_mm3": solid.Volume,
                "face_count": len(solid.Faces),
            },
        )
        return 0
    except Exception as exc:
        _write_metadata(
            metadata_path,
            {"status": "error", "error": str(exc), "traceback": traceback.format_exc()},
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
