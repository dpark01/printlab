from __future__ import annotations

from pathlib import Path

from printlab.toolchain import find_repo_root, load_pinned_tools


def test_find_repo_root_locates_tools_toml(repo_root: Path):
    nested = repo_root / "printlab" / "schemas"
    assert find_repo_root(nested) == repo_root


def test_load_pinned_tools_has_both_backends(repo_root: Path):
    pinned = load_pinned_tools(repo_root)
    assert "prusaslicer" in pinned
    assert "bambustudio" in pinned
    assert pinned["prusaslicer"]["version"]
    assert pinned["bambustudio"]["version"]
