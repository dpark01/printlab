"""Bambu Studio CLI backend: serves the user's actual printer, not the
reference/CI backend (see printlab.slicing.prusaslicer for that role).

Bambu Studio's self-reported slicing metrics are unreliable in practice: its
`--export-slicedata` side-channel JSON has been observed reporting
`total_used_g: 0.0` and `filament_density: 0` on a real slice, and even the
emitted G-code header's own `total filament weight [g]` comment is `0.00`.
printlab.gcode re-derives every metric except estimated time directly from
the G-code for exactly this reason (see printlab.gcode.parser).

Bambu's native settings are whole-preset JSON files that `inherits` from a
system profile database bundled *inside the installed BambuStudio app*, not
from the committed file alone -- so cross-machine Tier-1 reproducibility for
this backend depends on both machines running the same pinned BambuStudio
version (recorded in run_manifest.json's tool_versions), not solely on the
committed profiles/native/bambu/ files. The small knob allowlist is applied
by writing a patched copy of the process JSON (overriding its top-level
keys, which is exactly how Bambu's own preset inheritance overrides work)
rather than via separate CLI flags, since Bambu Studio's CLI has no
per-setting override flags.
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

_VERSION_LINE_PREFIX = "BambuStudio-"
_BRIM_WIDTH_MM = "5"


class BambuStudioBackend(PrusaLikeBackend):
    name = "bambu"
    binary_name = "BambuStudio"
    candidate_paths = (
        Path.home() / "Applications" / "BambuStudio.app" / "Contents" / "MacOS" / "BambuStudio",
        Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"),
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
            return Capabilities(backend=self.name, available=False, notes="BambuStudio binary not found")
        return Capabilities(
            backend=self.name,
            available=True,
            version=self._version(binary),
            deterministic=False,
            emits_reliable_gcode_stats=False,
            supports_bambu_machines=True,
            supports_orientation=True,
            supports_supports=True,
            notes="Self-reported slicing metrics (result.json, G-code header filament "
            "weight) have been observed to be zeroed/unreliable; printlab.gcode "
            "re-derives all metrics except estimated time. Native profile "
            "resolution depends on the installed BambuStudio version's bundled "
            "system profile database, not solely on the committed bundle file.",
        )

    def _patched_process_settings(
        self, process_native_path: Path, overrides: dict[str, str], output_dir: Path
    ) -> Path:
        with process_native_path.open("r") as fh:
            data = json.load(fh)
        data.update(overrides)
        patched_path = output_dir / "resolved_process.bambu.json"
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
                        message="BambuStudio binary not found on this machine.",
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
                        message="Printer/material/process profile is missing a 'bambu' native_bundle entry.",
                        stage="slicing",
                    )
                ],
            )

        resolved = resolve_process_overrides(request, process)
        settings = resolved.as_dict()

        output_dir = Path(request.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        input_model = Path(request.input_model).resolve()

        # Bambu preset JSONs are flat key overrides on top of an inherited
        # base -- patching these top-level keys on a copy is the same
        # mechanism Bambu's own preset system uses, applied programmatically.
        bambu_overrides = {
            "layer_height": str(settings["layer_height_mm"]),
            "sparse_infill_density": f"{settings['infill_percent']}%",
            "enable_support": "1" if settings["supports"] else "0",
            "brim_width": _BRIM_WIDTH_MM if settings["brim"] else "0",
        }
        if settings["wall_count"] is not None:
            bambu_overrides["wall_loops"] = str(settings["wall_count"])
        patched_process_path = self._patched_process_settings(Path(process_path), bambu_overrides, output_dir)

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
        # comparable to one computed on another. Combined with `settings`
        # (the override values patched on top), this fully determines the
        # effective config without needing to hash the generated patched copy.
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
        # signal, not the exit code -- see printlab.slicing.prusaslicer for
        # why (never trust a slicer's self-reported status, applied to exit
        # codes as much as to metrics).
        if not gcode_path.is_file():
            return SliceResult(
                backend=self.name,
                backend_version=backend_version,
                status=Status.ERROR,
                errors=[
                    ArtifactError(
                        code="slice_failed",
                        message=(result.stderr or result.stdout or "BambuStudio exited non-zero").strip()[
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
                f"BambuStudio exited with code {result.returncode} but wrote G-code anyway: "
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
