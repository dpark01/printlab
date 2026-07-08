"""OrcaSlicer CLI backend.

Added after an evidence-based spike, not on reputation: OrcaSlicer's CLI
flag surface and G-code conventions were found to be nearly identical to
Bambu Studio's (same `--load-settings`/`--load-filaments` model, same
`; CHANGE_LAYER` / `M83` G-code style, no per-setting override flags either
-- our JSON-patching override mechanism was verified to work unchanged
against OrcaSlicer). The genuine, verified advantage is that OrcaSlicer
bundles a far broader vendor profile library (dozens of printer brands vs.
Bambu Studio's narrow BBL-focused set) while remaining Bambu-compatible, and
exposes more granular print-tuning keys in its config dump. Self-reported
metrics are just as unreliable as Bambu Studio's (observed directly:
`filament_density: 0` in its own G-code header) -- printlab.gcode re-derives
everything except estimated time here too.
"""

from __future__ import annotations

import json
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

_VERSION_LINE_PREFIX = "OrcaSlicer-"
_BRIM_WIDTH_MM = "5"


class OrcaSlicerBackend(PrusaLikeBackend):
    name = "orcaslicer"
    binary_name = "OrcaSlicer"
    candidate_paths = (
        Path.home() / "Applications" / "OrcaSlicer.app" / "Contents" / "MacOS" / "OrcaSlicer",
        Path("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
    )

    def _version(self, binary: Path) -> str | None:
        result = self.run_cli(binary, ["--help"], timeout=30)
        for line in result.stdout.splitlines():
            if line.startswith(_VERSION_LINE_PREFIX):
                return line[len(_VERSION_LINE_PREFIX) :].rstrip(":").strip()
        return None

    def detect(self) -> Capabilities:
        binary = self.find_binary()
        if binary is None:
            return Capabilities(backend=self.name, available=False, notes="OrcaSlicer binary not found")
        return Capabilities(
            backend=self.name,
            available=True,
            version=self._version(binary),
            deterministic=False,
            emits_reliable_gcode_stats=False,
            supports_bambu_machines=True,
            supports_orientation=True,
            supports_supports=True,
            notes="Self-reported slicing metrics have been observed to be zeroed/unreliable "
            "(same issue as Bambu Studio); printlab.gcode re-derives all metrics except "
            "estimated time. Bundles a much broader vendor profile library than Bambu "
            "Studio while remaining Bambu-compatible.",
        )

    def _patched_process_settings(
        self, process_native_path: Path, overrides: dict[str, str], output_dir: Path
    ) -> Path:
        with process_native_path.open("r") as fh:
            data = json.load(fh)
        data.update(overrides)
        patched_path = output_dir / "resolved_process.orcaslicer.json"
        with patched_path.open("w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        return patched_path

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
                        message="OrcaSlicer binary not found on this machine.",
                        stage="slicing",
                    )
                ],
            )

        # Resolved to absolute so behavior never depends on the caller's cwd
        # (native_bundle paths in profile YAML are relative to the repo root).
        machine_path = printer.native_bundle.get(self.name)
        filament_path = material.native_bundle.get(self.name)
        process_path = process.native_bundle.get(self.name)
        machine_path = Path(machine_path).resolve() if machine_path else None
        filament_path = Path(filament_path).resolve() if filament_path else None
        process_path = Path(process_path).resolve() if process_path else None
        if not (machine_path and filament_path and process_path):
            return SliceResult(
                backend=self.name,
                backend_version=self._version(binary) or "unknown",
                status=Status.ERROR,
                errors=[
                    ArtifactError(
                        code="native_bundle_missing",
                        message="Printer/material/process profile is missing an "
                        "'orcaslicer' native_bundle entry.",
                        stage="slicing",
                    )
                ],
            )

        resolved = resolve_process_overrides(request, process)
        settings = resolved.as_dict()

        output_dir = Path(request.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        input_model = Path(request.input_model).resolve()

        # Same flat key-override mechanism as Bambu Studio (verified to work
        # unchanged against OrcaSlicer) -- see printlab.slicing.bambu.
        orca_overrides = {
            "layer_height": str(settings["layer_height_mm"]),
            "sparse_infill_density": f"{settings['infill_percent']}%",
            "enable_support": "1" if settings["supports"] else "0",
            "brim_width": _BRIM_WIDTH_MM if settings["brim"] else "0",
        }
        if settings["wall_count"] is not None:
            orca_overrides["wall_loops"] = str(settings["wall_count"])
        patched_process_path = self._patched_process_settings(Path(process_path), orca_overrides, output_dir)

        args = [
            "--load-settings",
            f"{machine_path};{patched_process_path}",
            "--load-filaments",
            str(filament_path),
            "--slice",
            "1",
            "--export-3mf",
            "part.3mf",
            "--outputdir",
            str(output_dir),
            str(input_model),
        ]

        result = self.run_cli(binary, args, timeout=600)
        gcode_path = output_dir / "plate_1.gcode"

        # Content hashes of the base (pre-override) bundles, not absolute
        # paths: a hash computed on one machine/clone location must be
        # comparable to one computed on another.
        resolved_settings = {
            "native_bundle_hashes": {
                machine_path.name: hash_file(machine_path),
                filament_path.name: hash_file(filament_path),
                process_path.name: hash_file(process_path),
            },
            **settings,
        }
        resolved_settings_hash = sha256_hexdigest(
            canonical_json(normalize(resolved_settings)).encode("utf-8")
        )
        backend_version = self._version(binary) or "unknown"

        # The G-code file actually existing is the authoritative success
        # signal, not the exit code -- see printlab.slicing.prusaslicer.
        if not gcode_path.is_file():
            return SliceResult(
                backend=self.name,
                backend_version=backend_version,
                status=Status.ERROR,
                errors=[
                    ArtifactError(
                        code="slice_failed",
                        message=(result.stderr or result.stdout or "OrcaSlicer exited non-zero").strip()[
                            -2000:
                        ],
                        stage="slicing",
                        context={"returncode": result.returncode},
                    )
                ],
                resolved_settings=resolved_settings,
                resolved_settings_sha256=resolved_settings_hash,
            )

        warnings = []
        if result.returncode != 0:
            warnings.append(
                f"OrcaSlicer exited with code {result.returncode} but wrote G-code anyway: "
                + (result.stderr or result.stdout or "").strip()[-500:]
            )

        return SliceResult(
            backend=self.name,
            backend_version=backend_version,
            gcode_path=gcode_path,
            project_path=output_dir / "part.3mf",
            resolved_settings=resolved_settings,
            resolved_settings_sha256=resolved_settings_hash,
            status=Status.OK if not warnings else Status.WARNING,
            warnings=warnings,
        )
