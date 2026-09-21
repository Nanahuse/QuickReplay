"""Tests for release version comparison rules."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SPEC = spec_from_file_location(
    "release_version", Path(__file__).parents[1] / "tools" / "release_version.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
release_required = _MODULE.release_required
version_from_text = _MODULE.version_from_text


def _project(version: str) -> str:
    return f'[project]\nversion = "{version}"\n'


def test_same_version_does_not_release() -> None:
    assert not release_required("2.0.0", "2.0.0")


def test_changed_version_releases() -> None:
    assert release_required("2.0.0", "2.0.1")


def test_missing_previous_version_releases() -> None:
    assert release_required(None, "2.0.0")


def test_version_is_read_from_project_table() -> None:
    assert version_from_text(_project("2.0.0")) == "2.0.0"
