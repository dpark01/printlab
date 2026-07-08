"""Determinism: canonical JSON, normalization, and content hashing.

PrintLab does **not** promise byte-identical raw slicer output — that is an
explicit non-goal (Tier 3). Slicers embed timestamps, version strings, and
thumbnails; STL tessellation depends on the OCCT version. What PrintLab
promises instead:

  Tier 1 (the real contract): identical PrintLab version + pinned tool
    versions + identical input hashes => normalized artifacts are hash-
    identical and metrics match exactly. Enforced by this module.
  Tier 2: metrics stay within declared tolerances across tool *patch*
    versions. Enforced by golden tests asserting numeric tolerances, not by
    this module.
  Tier 3 (non-goal): raw byte-identical slicer output.

This module implements the normalization + hashing that Tier 1 rests on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

#: Keys that are inherently volatile (wall clock, host-specific, or a
#: fingerprint of a file this project doesn't control the determinism of) and
#: must never participate in a reproducibility hash, even though they are
#: still recorded elsewhere in an artifact for humans/agents to read.
#:
#: `gcode_sha256` belongs here alongside the timestamp fields because a
#: slicer's G-code embeds a wall-clock-generated header comment (see
#: printlab.gcode.parser docstring) -- the file's content hash is therefore
#: exactly as volatile as a timestamp, even though the *metrics* PrintLab
#: parses out of it are stable. Path fields (`input_path`, `gcode_path`,
#: `project_path`, `output_path`) are excluded too, so a hash computed on one
#: machine/clone location is comparable to one computed on another.
VOLATILE_KEYS: frozenset[str] = frozenset(
    {
        "created_at",
        "generated_at",
        "timestamp",
        "export_time",
        "prepare_time",
        "gcode_sha256",
        "input_path",
        "gcode_path",
        "project_path",
        "output_path",
    }
)

#: Floats are rounded to this many decimal places before hashing, to absorb
#: harmless platform/library floating point noise (trig functions, OCCT
#: tessellation) without hiding engineering-significant changes.
DEFAULT_FLOAT_NDIGITS = 6


def _normalize(value: Any, *, float_ndigits: int, drop_keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize(val, float_ndigits=float_ndigits, drop_keys=drop_keys)
            for key, val in value.items()
            if key not in drop_keys
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(v, float_ndigits=float_ndigits, drop_keys=drop_keys) for v in value]
    if isinstance(value, float):
        return round(value, float_ndigits)
    if isinstance(value, Path):
        return value.as_posix()
    return value


def normalize(
    data: dict[str, Any],
    *,
    float_ndigits: int = DEFAULT_FLOAT_NDIGITS,
    drop_keys: frozenset[str] = VOLATILE_KEYS,
) -> dict[str, Any]:
    """Recursively strip volatile keys and round floats to a fixed precision.

    Note: this does not attempt to detect which lists are semantically
    unordered (e.g. a set of warnings vs. an ordered list of checks) — it only
    handles the two normalization concerns that are safe to apply blindly.
    Order-sensitive artifact fields must be constructed in a stable order by
    the producing stage.
    """
    return _normalize(data, float_ndigits=float_ndigits, drop_keys=drop_keys)


def canonical_json(data: dict[str, Any]) -> str:
    """Serialize to canonical JSON: sorted keys, fixed separators, no NaN/Infinity."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hexdigest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    """SHA-256 of a file's raw bytes — used to fingerprint inputs and profiles."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_mapping(data: dict[str, Any], **normalize_kwargs: Any) -> str:
    """Normalize a plain JSON-able mapping and return its content hash."""
    normalized = normalize(data, **normalize_kwargs)
    return sha256_hexdigest(canonical_json(normalized).encode("utf-8"))


def hash_artifact(model: BaseModel, **normalize_kwargs: Any) -> str:
    """Normalize a Pydantic artifact's JSON-mode dump and hash it.

    This is the Tier-1 reproducibility primitive: two runs with identical
    inputs and pinned tool versions must produce artifacts whose
    ``hash_artifact()`` is identical.
    """
    return hash_mapping(model.model_dump(mode="json"), **normalize_kwargs)
