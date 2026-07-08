"""Finding and running the CalculiX solver (`ccx`).

Mirrors printlab.slicing.base.PrusaLikeBackend's binary-discovery and
subprocess conventions: probe a few known absolute paths, fall back to a PATH
lookup, and always invoke as a list (never shell=True) with an explicit
timeout. The costerwi Homebrew tap installs a version-suffixed binary
(`ccx_2.23`), not a bare `ccx`, so discovery accepts both.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

#: Directories to probe before a PATH lookup (Homebrew on Apple Silicon / Intel).
_CCX_CANDIDATE_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))

#: Binary names to try on PATH; the tap ships version-suffixed names too.
_CCX_BINARY_NAMES = ("ccx", "ccx_2.23")

_VERSION_RE = re.compile(r"[Vv]ersion\s+([0-9][0-9.]*)")


def find_ccx_binary() -> Path | None:
    """Absolute path to the CalculiX executable, or None if not installed."""
    for directory in _CCX_CANDIDATE_DIRS:
        bare = directory / "ccx"
        if bare.is_file():
            return bare
        for versioned in sorted(directory.glob("ccx_*")):
            if versioned.is_file():
                return versioned
    for name in _CCX_BINARY_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def detect_ccx_version(binary: Path | None = None) -> str | None:
    """Version string CalculiX reports, e.g. "2.23". `ccx -v` prints a single
    line "This is Version 2.23"; parse the number out of it. None if ccx isn't
    found or prints nothing recognizable."""
    binary = binary or find_ccx_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [str(binary), "-v"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_RE.search(f"{result.stdout}\n{result.stderr}")
    return match.group(1) if match else None


def run_ccx(inp_path: Path, *, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    """Run `ccx <jobname>` in the deck's directory (jobname is the .inp stem,
    without extension -- CalculiX appends .inp itself and writes .frd/.dat/.sta
    alongside it). List-form args, no shell, explicit timeout, check=False so
    the caller can inspect a nonzero exit."""
    inp_path = Path(inp_path)
    binary = find_ccx_binary()
    if binary is None:
        raise FileNotFoundError("CalculiX 'ccx' binary not found on PATH or in known locations")
    return subprocess.run(
        [str(binary), inp_path.stem],
        cwd=str(inp_path.parent),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
