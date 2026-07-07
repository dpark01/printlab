"""PrusaSlicer CLI backend: the reference backend for CI and determinism.

PrusaSlicer's CLI is stable, headless-clean, and lets us pin the one real
source of slicer RNG (seam position) explicitly rather than trust a default
that could change between versions. Native settings are three flat `.ini`
files (see profiles/native/prusaslicer/) loaded in the resolution order
printer -> material -> process, with the small knob allowlist applied last so
it always wins.
"""

from __future__ import annotations

from pathlib import Path

from printlab.determinism import canonical_json, hash_file, normalize, sha256_hexdigest
from printlab.profiles import resolve_process_overrides
from printlab.schemas import (
    ArtifactError,
    Capabilities,
    MaterialProfile,
    PrinterProfile,
    ProcessProfile,
    SliceRequest,
    SliceResult,
    Status,
)
from printlab.slicing.base import PrusaLikeBackend

_VERSION_PREFIX = "PrusaSlicer-"
_BRIM_WIDTH_MM = "5"

# Pinned explicitly rather than left at PrusaSlicer's (currently identical)
# default, so a future PrusaSlicer default change can't silently reintroduce
# random seam placement without a deliberate PrintLab version bump.
_SEAM_POSITION = "aligned"


class PrusaSlicerBackend(PrusaLikeBackend):
    name = "prusaslicer"
    binary_name = "prusa-slicer"
    candidate_paths = (
        Path.home() / "Applications" / "PrusaSlicer.app" / "Contents" / "MacOS" / "PrusaSlicer",
        Path("/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"),
    )

    def _version(self, binary: Path) -> str | None:
        result = self.run_cli(binary, ["--help"], timeout=30)
        for line in result.stdout.splitlines():
            if line.startswith(_VERSION_PREFIX):
                return line[len(_VERSION_PREFIX) :].split(" ", 1)[0].strip()
        return None

    def detect(self) -> Capabilities:
        binary = self.find_binary()
        if binary is None:
            return Capabilities(backend=self.name, available=False, notes="PrusaSlicer binary not found")
        return Capabilities(
            backend=self.name,
            available=True,
            version=self._version(binary),
            deterministic=True,
            emits_reliable_gcode_stats=True,
            supports_bambu_machines=False,
            supports_orientation=False,
            supports_supports=True,
            notes="Reference backend for CI/determinism. Seam position is pinned "
            f"to '{_SEAM_POSITION}' (never random).",
        )

    def slice(
        self,
        request: SliceRequest,
        *,
        printer: PrinterProfile,
        material: MaterialProfile,
        process: ProcessProfile,
    ) -> SliceResult:
        binary = self.find_binary()
        if binary is None:
            return SliceResult(
                backend=self.name,
                backend_version="unknown",
                status=Status.ERROR,
                errors=[
                    ArtifactError(
                        code="binary_not_found",
                        message="PrusaSlicer binary not found on this machine.",
                        stage="slicing",
                    )
                ],
            )

        # Resolved to absolute so behavior never depends on the caller's cwd
        # (native_bundle paths in profile YAML are relative to the repo root).
        native_bundle_paths = [
            Path(path).resolve()
            for path in (
                printer.native_bundle.get(self.name),
                material.native_bundle.get(self.name),
                process.native_bundle.get(self.name),
            )
            if path is not None
        ]

        resolved = resolve_process_overrides(request, process)
        settings = resolved.as_dict()

        output_dir = Path(request.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        gcode_path = output_dir / "part.gcode"
        input_model = Path(request.input_model).resolve()

        args: list[str] = []
        for bundle_path in native_bundle_paths:
            args += ["--load", str(bundle_path)]
        args += [
            "--layer-height",
            str(settings["layer_height_mm"]),
            "--first-layer-height",
            str(settings["layer_height_mm"]),
            "--fill-density",
            f"{settings['infill_percent']}%",
            "--seam-position",
            _SEAM_POSITION,
            "--brim-width",
            _BRIM_WIDTH_MM if settings["brim"] else "0",
        ]
        if settings["supports"]:
            args.append("--support-material")
        args += [
            "--export-gcode",
            "--output",
            str(gcode_path),
            str(input_model),
        ]

        result = self.run_cli(binary, args, cwd=output_dir, timeout=600)

        # Content hashes, not absolute paths: a hash computed on one machine
        # or clone location must be comparable to one computed on another.
        resolved_settings = {
            "native_bundle_hashes": {p.name: hash_file(p) for p in native_bundle_paths},
            "seam_position": _SEAM_POSITION,
            **settings,
        }
        resolved_settings_hash = sha256_hexdigest(
            canonical_json(normalize(resolved_settings)).encode("utf-8")
        )
        backend_version = self._version(binary) or "unknown"

        if result.returncode != 0 or not gcode_path.is_file():
            return SliceResult(
                backend=self.name,
                backend_version=backend_version,
                status=Status.ERROR,
                errors=[
                    ArtifactError(
                        code="slice_failed",
                        message=(result.stderr or result.stdout or "PrusaSlicer exited non-zero").strip()[
                            -2000:
                        ],
                        stage="slicing",
                        context={"returncode": result.returncode},
                    )
                ],
                resolved_settings=resolved_settings,
                resolved_settings_sha256=resolved_settings_hash,
            )

        return SliceResult(
            backend=self.name,
            backend_version=backend_version,
            gcode_path=gcode_path,
            resolved_settings=resolved_settings,
            resolved_settings_sha256=resolved_settings_hash,
            status=Status.OK,
        )
