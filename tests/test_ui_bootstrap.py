"""Desktop bootstrap: configuration, settings and application wiring."""

from pathlib import Path

import pytest

from quickreplay.application.controller import ApplicationController
from quickreplay.configuration.errors import ConfigurationParseError
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import NdiInputConfig
from quickreplay.ui.bootstrap import bootstrap_application
from quickreplay.ui.bridge import ApplicationUiBridge
from quickreplay.ui.paths import resolve_storage_paths


def _paths(tmp_path: Path):
    return resolve_storage_paths(
        data_directory=tmp_path / "data", cache_directory=tmp_path / "cache"
    )


def test_bootstrap_builds_defaults(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    boot = bootstrap_application(paths=paths)

    assert boot.store.path == paths.config_path
    assert boot.config == QuickReplayConfig()
    assert isinstance(boot.controller, ApplicationController)
    assert isinstance(boot.bridge, ApplicationUiBridge)
    assert not paths.config_path.exists()  # first run does not create the file


def test_bootstrap_loads_existing_config(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.data_directory.mkdir(parents=True)
    ConfigurationStore(paths.config_path).save(QuickReplayConfig(input=NdiInputConfig("OBS")))

    boot = bootstrap_application(paths=paths)

    assert boot.config.input == NdiInputConfig("OBS")


def test_bootstrap_broken_config_raises(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.data_directory.mkdir(parents=True)
    paths.config_path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(ConfigurationParseError):
        bootstrap_application(paths=paths)


def test_bootstrap_runtime_directory(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    boot = bootstrap_application(paths=paths)

    settings = boot.controller  # constructing does not start the worker
    assert settings is not None
    assert paths.runtime_directory == tmp_path / "cache" / "runtime"
