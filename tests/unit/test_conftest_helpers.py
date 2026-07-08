"""Regression tests for tests.conftest's own test-infrastructure helpers.

skip_unless_importable() is what caught out a real CI failure: gmsh's C
extension dlopen()s libGLU at import time, raising OSError (not ImportError)
on an environment missing that shared library -- plain pytest.importorskip()
only catches ImportError, so it turned a missing optional native lib into a
hard collection error instead of a clean skip.
"""

from __future__ import annotations

import importlib

import pytest

from tests.conftest import skip_unless_importable


def test_skips_on_import_error():
    with pytest.raises(pytest.skip.Exception):
        skip_unless_importable("this_module_does_not_exist_anywhere")


def test_skips_on_os_error_not_just_import_error(monkeypatch):
    """The actual regression: a module whose import raises OSError (e.g. a
    missing shared library, like gmsh's libGLU dependency) must also be
    treated as a skip, not an error."""

    def _raise_oserror(_name):
        raise OSError("libGLU.so.1: cannot open shared object file: No such file or directory")

    monkeypatch.setattr(importlib, "import_module", _raise_oserror)

    with pytest.raises(pytest.skip.Exception):
        skip_unless_importable("irrelevant_module_name")
