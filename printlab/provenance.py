"""Provenance: builds run_manifest.json, the artifact that makes a run auditable.

This is the piece SETUP.md's original design omitted entirely. It records
what actually produced a set of artifacts (tool versions, input/profile
hashes, resolved settings), so an agent — or a human — can diff two manifests
to answer "why did the metrics change between run A and run B?" instead of
re-deriving it from scratch.
"""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from printlab.determinism import canonical_json, hash_file, normalize, sha256_hexdigest
from printlab.schemas import RunManifest

#: Python-distributed tools whose output can affect reproducibility. Native
#: slicer binaries are versioned separately by printlab.slicing backends and
#: merged in via the `tool_versions` argument to build_run_manifest().
_TRACKED_PACKAGES = ("printlab", "cadquery", "cadquery-ocp", "trimesh", "pydantic", "numpy")


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git_commit(repo_root: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def collect_python_tool_versions() -> dict[str, str]:
    """Versions of the Python libraries whose output affects reproducibility."""
    versions: dict[str, str] = {}
    for name in _TRACKED_PACKAGES:
        version = _package_version(name)
        if version:
            versions[name] = version
    return versions


def hash_inputs(paths: dict[str, Path | None]) -> dict[str, str]:
    """SHA-256 each named input path (CAD source, profiles, ...) that exists."""
    return {name: hash_file(path) for name, path in paths.items() if path and Path(path).is_file()}


def build_run_manifest(
    *,
    tool_versions: dict[str, str] | None = None,
    input_hashes: dict[str, str] | None = None,
    profile_hashes: dict[str, str] | None = None,
    resolved_settings: dict[str, Any] | None = None,
    repo_root: Path | None = None,
    created_at: str | None = None,
) -> RunManifest:
    """Build a RunManifest for the current run. Call finalize_manifest() once
    all stage artifacts exist, to attach their content hashes."""
    all_tool_versions = collect_python_tool_versions()
    if tool_versions:
        all_tool_versions.update(tool_versions)

    resolved_settings_hash = None
    if resolved_settings is not None:
        resolved_settings_hash = sha256_hexdigest(
            canonical_json(normalize(resolved_settings)).encode("utf-8")
        )

    return RunManifest(
        printlab_version=_package_version("printlab") or "0.0.0-dev",
        git_commit=_git_commit(repo_root),
        platform=platform.platform(),
        created_at=created_at or datetime.now(UTC).isoformat(),
        tool_versions=all_tool_versions,
        input_hashes=input_hashes or {},
        profile_hashes=profile_hashes or {},
        resolved_settings_hash=resolved_settings_hash,
    )


def finalize_manifest(manifest: RunManifest, artifact_hashes: dict[str, str]) -> RunManifest:
    """Attach per-artifact content hashes and an overall content hash.

    Call once every stage in a pipeline run has produced its artifact, so the
    manifest can summarize the whole run in one comparable hash.
    """
    updated = manifest.model_copy(update={"artifact_hashes": dict(artifact_hashes)})
    content_hash = sha256_hexdigest(
        canonical_json(normalize({"artifact_hashes": updated.artifact_hashes})).encode("utf-8")
    )
    return updated.model_copy(update={"content_hash": content_hash})
