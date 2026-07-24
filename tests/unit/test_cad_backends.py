from pathlib import Path

import pytest

from printlab import pipeline
from printlab.cad import CadBuildError, available_cad_backend_names, get_cad_backend


def _write_profiles_config(example_dir: Path, part_table: str) -> None:
    (example_dir / "printlab.toml").write_text(
        part_table
        + """

[profiles]
printer = "printer.yaml"
material = "material.yaml"
process = "process.yaml"
"""
    )


def test_registry_exposes_cadquery() -> None:
    assert available_cad_backend_names() == ("cadquery", "openscad")
    assert get_cad_backend("cadquery").name == "cadquery"


def test_registry_rejects_unknown_backend() -> None:
    with pytest.raises(CadBuildError, match="unknown CAD backend 'unknown'"):
        get_cad_backend("unknown")


def test_legacy_module_config_defaults_to_cadquery(tmp_path: Path) -> None:
    _write_profiles_config(tmp_path, '[part]\nname = "widget"\nmodule = "part.py"\n')

    config = pipeline.load_part_config(tmp_path, repo_root=tmp_path)

    assert config.cad_backend == "cadquery"
    assert config.source_path == tmp_path / "part.py"
    assert config.build_function == "build"
    assert config.part_py == config.source_path


def test_canonical_source_config_selects_backend(tmp_path: Path) -> None:
    _write_profiles_config(
        tmp_path,
        '[part]\nname = "widget"\ncad_backend = "cadquery"\nsource = "model.py"\nfunction = "closed"\n',
    )

    config = pipeline.load_part_config(tmp_path, repo_root=tmp_path)

    assert config.source_path == tmp_path / "model.py"
    assert config.build_function == "closed"


def test_openscad_config_loads_backend_options_without_python_function(tmp_path: Path) -> None:
    _write_profiles_config(
        tmp_path,
        """[part]
name = "widget"
cad_backend = "openscad"
source = "part.scad"

[part.openscad]
defines = { width = 12 }
""",
    )

    config = pipeline.load_part_config(tmp_path, repo_root=tmp_path)

    assert config.cad_backend == "openscad"
    assert config.build_function is None
    assert config.cad_options == {"defines": {"width": 12}}


def test_openscad_config_rejects_python_function(tmp_path: Path) -> None:
    _write_profiles_config(
        tmp_path,
        '[part]\nname = "widget"\ncad_backend = "openscad"\nsource = "part.scad"\nfunction = "build"\n',
    )

    with pytest.raises(pipeline.PipelineError, match="function is only valid for the cadquery"):
        pipeline.load_part_config(tmp_path, repo_root=tmp_path)


def test_config_rejects_unknown_cad_backend(tmp_path: Path) -> None:
    _write_profiles_config(
        tmp_path,
        '[part]\nname = "widget"\ncad_backend = "unknown"\nsource = "part.cad"\n',
    )

    with pytest.raises(pipeline.PipelineError, match="unknown CAD backend"):
        pipeline.load_part_config(tmp_path, repo_root=tmp_path)


def test_build_function_override_rejects_openscad(tmp_path: Path) -> None:
    _write_profiles_config(
        tmp_path,
        '[part]\nname = "widget"\ncad_backend = "openscad"\nsource = "part.scad"\n',
    )
    config = pipeline.load_part_config(tmp_path, repo_root=tmp_path)

    with pytest.raises(pipeline.PipelineError, match="only valid for the cadquery backend"):
        pipeline.override_build_function(config, "build")
