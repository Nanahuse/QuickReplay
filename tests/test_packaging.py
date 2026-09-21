"""Headless checks for the Windows packaging entry point and configuration."""

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_packaging_entry_point_is_thin_and_has_no_import_side_effect() -> None:
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert [node.name for node in tree.body if isinstance(node, ast.FunctionDef)] == []
    assert "multiprocessing.freeze_support()" in source
    assert "run()" in source
    assert "bootstrap_application" not in source
    assert "MainView" not in source


def test_flet_windows_packaging_configuration() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    flet = config["tool"]["flet"]

    assert flet["product"] == "QuickReplay"
    assert flet["app"] == {"path": "src", "module": "main"}
    assert flet["windows"]["artifact"] == "QuickReplay"
    assert flet["windows"]["compile"] == {"packages": False}
    assert flet["windows"]["cleanup"] == {"packages": False}
