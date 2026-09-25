"""Standalone About window content, navigation and metadata tests."""

from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import cast

import flet as ft
import pytest

from quickreplay.ui import about
from quickreplay.ui.about import (
    GITHUB_URL,
    MIT_LICENSE,
    THIRD_PARTY_LICENSES,
    THIRD_PARTY_NOTICE,
    application_version,
    build_about_ui,
)


class StubPage:
    def __init__(self) -> None:
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


def _controls(control: ft.Control) -> list[ft.Control]:
    result = [control]
    if isinstance(control, (ft.Column, ft.Row)):
        for child in control.controls:
            result.extend(_controls(child))
    if isinstance(control, ft.Container) and control.content is not None:
        result.extend(_controls(control.content))
    return result


def _click(button: ft.Control) -> None:
    handler = getattr(button, "on_click", None)
    assert handler is not None
    cast(Callable[[ft.Event], object], handler)(cast(ft.Event, object()))


def _make_about() -> tuple[ft.Control, StubPage]:
    page = StubPage()
    return build_about_ui(cast(ft.Page, page)), page


def _text_values(control: ft.Control) -> list[str]:
    return [child.value for child in _controls(control) if isinstance(child, ft.Text)]


def test_about_identity_and_quickreplay_license_are_available_offline() -> None:
    ui, _page = _make_about()
    texts = _text_values(ui)
    buttons = [child for child in _controls(ui) if isinstance(child, ft.TextButton)]

    assert "QuickReplay" in texts
    assert f"Version {version('quickreplay')} · © 2022 Nanahuse" in texts
    assert any(button.url == GITHUB_URL for button in buttons)
    assert MIT_LICENSE in texts
    assert any(isinstance(child, ft.OutlinedButton) for child in _controls(ui))


def test_third_party_license_list_and_notice_view_are_navigable() -> None:
    ui, page = _make_about()
    third_party_tab = next(
        control
        for control in _controls(ui)
        if isinstance(control, ft.OutlinedButton) and control.content == "Third-party Licenses"
    )
    _click(third_party_tab)

    texts = _text_values(ui)
    assert "Third-party Licenses" in texts
    for name, license_name, _url in THIRD_PARTY_LICENSES:
        assert name in texts
        assert license_name in texts
    assert sum(
        isinstance(child, ft.TextButton) and child.content == "Website" for child in _controls(ui)
    ) == len(THIRD_PARTY_LICENSES)

    notices_button = next(
        child
        for child in _controls(ui)
        if isinstance(child, ft.TextButton) and child.content == "View third-party notices"
    )
    _click(notices_button)
    assert THIRD_PARTY_NOTICE in _text_values(ui)
    assert page.updates == 2


def test_local_license_text_matches_distributed_license_files() -> None:
    repository = Path(__file__).parents[1]
    assert MIT_LICENSE == (repository / "LICENSE").read_text(encoding="utf-8").rstrip()
    assert (
        THIRD_PARTY_NOTICE
        == (repository / "LICENSE_ThirdParty.md").read_text(encoding="utf-8").rstrip()
    )


def test_application_version_comes_from_installed_project_metadata() -> None:
    assert application_version() == version("quickreplay")


def test_application_version_uses_packaged_windows_version_when_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_metadata(_distribution_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(about, "version", missing_metadata)
    monkeypatch.setattr(about, "_windows_executable_version", lambda: "2.0.0")

    assert application_version() == "2.0.0"
