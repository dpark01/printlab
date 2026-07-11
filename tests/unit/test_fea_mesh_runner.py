"""Fast-lane tests for printlab.fea.mesh_runner -- the subprocess-isolation
layer added for issue #4. Monkeypatches subprocess.run so these never invoke
gmsh/the CAD kernel; the real end-to-end meshing behavior (still numerically
identical to pre-isolation) is covered by tests/integration/test_fea_hook.py.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import numpy as np
import pytest

from printlab.fea import mesh_runner


def test_run_mesh_worker_raises_module_not_found_when_gmsh_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "gmsh" else object())
    calls: list = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))

    with pytest.raises(ModuleNotFoundError, match="fea"):
        mesh_runner.run_mesh_worker(tmp_path / "part.step")

    assert calls == []  # must short-circuit before ever spawning a subprocess


def test_run_mesh_worker_raises_runtime_error_on_worker_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="Invalid boundary mesh")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Invalid boundary mesh"):
        mesh_runner.run_mesh_worker(tmp_path / "part.step")


def test_run_mesh_worker_raises_runtime_error_on_missing_output_despite_zero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="no usable mesh"):
        mesh_runner.run_mesh_worker(tmp_path / "part.step")


def test_run_mesh_worker_raises_runtime_error_on_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 300))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out"):
        mesh_runner.run_mesh_worker(tmp_path / "part.step", timeout=1.0)


def test_run_mesh_worker_returns_parsed_result_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def fake_run(args, **kwargs):
        output_npz_path = Path(args[4])
        np.savez(
            output_npz_path,
            nodes=np.zeros((3, 3)),
            elements=np.zeros((1, 4), dtype=np.int64),
            resolved_mesh_size_mm=np.float64(1.23),
        )
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    nodes, elements, resolved_mesh_size_mm = mesh_runner.run_mesh_worker(
        tmp_path / "part.step", mesh_size_mm=None
    )

    assert nodes.shape == (3, 3)
    assert elements.shape == (1, 4)
    assert resolved_mesh_size_mm == pytest.approx(1.23)


def test_run_mesh_worker_passes_mesh_size_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        output_npz_path = Path(args[4])
        np.savez(
            output_npz_path,
            nodes=np.zeros((1, 3)),
            elements=np.zeros((1, 4), dtype=np.int64),
            resolved_mesh_size_mm=np.float64(0.25),
        )
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    mesh_runner.run_mesh_worker(tmp_path / "part.step", mesh_size_mm=0.25)

    assert "--mesh-size" in captured["args"]
    assert captured["args"][captured["args"].index("--mesh-size") + 1] == "0.25"
