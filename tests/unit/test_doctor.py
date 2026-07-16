from __future__ import annotations

import pytest
import typer

from printlab.cli import main


def test_doctor_strict_fails_for_incomplete_toolchain(monkeypatch, capsys):
    monkeypatch.setattr(main, "load_pinned_tools", lambda: {"calculix": {"version": "2.23"}})
    monkeypatch.setattr(main, "available_backend_names", lambda: ())
    monkeypatch.setattr(main, "detect_all", lambda: {})
    monkeypatch.setattr(
        main,
        "detect_openscad_toolchain",
        lambda: {
            "openscad": {"available": False, "version": None, "binary": None, "notes": "not found"},
            "freecad": {"available": False, "version": None, "binary": None, "notes": "not found"},
        },
    )
    monkeypatch.setattr(main, "find_ccx_binary", lambda: None)

    with pytest.raises(typer.Exit) as exc_info:
        main.doctor(strict=True)

    assert exc_info.value.exit_code == 1
    assert "[MISSING] openscad" in capsys.readouterr().out
