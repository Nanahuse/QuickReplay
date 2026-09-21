"""Flet storage path resolution."""

from pathlib import Path

import pytest

from quickreplay.ui.paths import (
    CACHE_ENVIRONMENT_VARIABLE,
    DATA_ENVIRONMENT_VARIABLE,
    StoragePathError,
    resolve_storage_paths,
    storage_paths_from_environment,
)


def test_injected_paths_build_config_and_runtime(tmp_path: Path) -> None:
    data = tmp_path / "data"
    cache = tmp_path / "cache"

    paths = resolve_storage_paths(data_directory=data, cache_directory=cache)

    assert paths.config_path == data / "config.json"
    assert paths.runtime_directory == cache / "runtime"


def test_environment_paths(tmp_path: Path) -> None:
    environ = {
        DATA_ENVIRONMENT_VARIABLE: str(tmp_path / "d"),
        CACHE_ENVIRONMENT_VARIABLE: str(tmp_path / "c"),
    }

    paths = storage_paths_from_environment(environ)

    assert paths.config_path == tmp_path / "d" / "config.json"
    assert paths.runtime_directory == tmp_path / "c" / "runtime"


def test_missing_environment_is_an_error() -> None:
    with pytest.raises(StoragePathError):
        storage_paths_from_environment({})


def test_partial_environment_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(StoragePathError):
        storage_paths_from_environment({DATA_ENVIRONMENT_VARIABLE: str(tmp_path)})
