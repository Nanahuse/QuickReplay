"""Desktop bootstrap: configuration, settings and application wiring."""

from pathlib import Path
from typing import Any, cast

import flet as ft
import pytest

from quickreplay.application.controller import ApplicationController
from quickreplay.configuration.errors import ConfigurationParseError
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.input.models import NdiInputConfig
from quickreplay.ui.app import _configure_window, _show_startup_error, run
from quickreplay.ui.bootstrap import bootstrap_application
from quickreplay.ui.bridge import ApplicationUiBridge
from quickreplay.ui.main_view import WINDOW_SIZES
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
    captured: list[Any] = []

    def controller_factory(settings: Any) -> Any:
        captured.append(settings)
        return object()

    bootstrap_application(paths=paths, controller_factory=controller_factory)

    assert len(captured) == 1
    settings = captured[0]
    assert settings.worker is not None
    assert settings.worker.working_directory == paths.runtime_directory


def test_initial_window_uses_setup_size_and_disables_resize() -> None:
    class Window:
        width = 0
        height = 0
        visible = True
        resizable = True
        maximizable = True

    class Page:
        title = ""
        window = Window()

    page = Page()

    _configure_window(cast(ft.Page, page))

    assert page.title == "QuickReplay"
    assert (page.window.width, page.window.height) == WINDOW_SIZES["setup"]
    assert page.window.visible is False
    assert page.window.resizable is False
    assert page.window.maximizable is False


def test_startup_error_shows_window_at_configured_size() -> None:
    class Window:
        width = WINDOW_SIZES["setup"][0]
        height = WINDOW_SIZES["setup"][1]
        visible = False

    class Page:
        window = Window()
        controls: list[ft.Control] = []
        updates = 0

        def add(self, control: ft.Control) -> None:
            self.controls.append(control)

        def update(self) -> None:
            self.updates += 1

    page = Page()

    _show_startup_error(cast(ft.Page, page), "startup failed")

    assert page.window.visible is True
    assert len(page.controls) == 1
    assert page.updates == 1


def test_run_starts_desktop_view_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(main, **kwargs) -> None:
        captured["main"] = main
        captured.update(kwargs)

    monkeypatch.setattr(ft, "run", fake_run)

    run()

    assert captured["main"] is not None
    assert captured["view"] is ft.AppView.FLET_APP_HIDDEN
