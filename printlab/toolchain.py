"""Native toolchain pinning: tools.toml declares which slicer versions
PrintLab's reproducibility contract is pinned against. Python dependencies
are pinned separately via uv.lock (see docs/environment.md, layer 1).
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    current = Path(start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "tools.toml").is_file():
            return candidate
    raise FileNotFoundError("could not find tools.toml in this or any parent directory")


def load_pinned_tools(repo_root: Path | None = None) -> dict[str, dict]:
    root = repo_root if repo_root is not None else find_repo_root()
    with (root / "tools.toml").open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tools", {})
