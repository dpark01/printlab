from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


def skip_unless_importable(module_name: str) -> None:
    """Like `pytest.importorskip`, but also treats OSError as a skip.

    Needed for `gmsh`: its C extension dlopen()s libGLU at import time --
    even though we only use its headless meshing API, never its GUI/OpenGL
    viewer -- so an environment missing that shared library (observed on a
    bare Ubuntu CI runner: "libGLU.so.1: cannot open shared object file")
    raises OSError, not ImportError. `pytest.importorskip` alone only
    catches ImportError, so this would otherwise be a hard collection error
    instead of a clean skip, exactly the failure mode this project's other
    capability-gated tests are designed to avoid.
    """
    try:
        importlib.import_module(module_name)
    except (ImportError, OSError) as exc:
        pytest.skip(f"{module_name} is not importable here: {exc}")
