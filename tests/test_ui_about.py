"""Offline About dialog content, navigation and metadata tests."""

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
    THIRD_PARTY_NOTICE,
    application_version,
    build_about_dialog,
)


def _controls(control: ft.Control) -> list[ft.Control]:
    result = [control]
    if isinstance(control, (ft.Column, ft.Row)):
        for child in control.controls:
            result.extend(_controls(child))
    if isinstance(control, ft.Container) and control.content is not None:
        result.extend(_controls(control.content))
    return result


def _buttons(control: ft.Control) -> list[ft.TextButton]:
    return [child for child in _controls(control) if isinstance(child, ft.TextButton)]


def _title(dialog: ft.AlertDialog) -> str:
    return cast(ft.Text, dialog.title).value


def _action_labels(dialog: ft.AlertDialog) -> list[str]:
    return [cast(str, cast(ft.TextButton, action).content) for action in dialog.actions]


def _click(button: ft.TextButton) -> None:
    assert button.on_click is not None
    handler = cast(Callable[[ft.Event], object], button.on_click)
    handler(cast(ft.Event, object()))


def _make_dialog() -> ft.AlertDialog:
    return build_about_dialog(lambda _event: None, lambda: None)


def test_about_top_is_compact_and_links_to_app_license_screens() -> None:
    dialog = _make_dialog()
    controls = _controls(cast(ft.Control, dialog.content))
    texts = [control.value for control in controls if isinstance(control, ft.Text)]
    buttons = _buttons(cast(ft.Control, dialog.content))

    assert dialog.modal is True
    assert _title(dialog) == "About"
    assert "QuickReplay" in texts
    assert f"Version {version('quickreplay')}" in texts
    assert "Copyright © 2022 Nanahuse" in texts
    assert "Licenses" in texts
    assert "MIT License" in texts
    assert "Third-party licenses" in texts
    assert MIT_LICENSE not in texts
    assert any(button.url == GITHUB_URL for button in buttons)
    assert len([button for button in buttons if button.content == "View"]) == 2
    assert _action_labels(dialog) == ["Close"]

    content = cast(ft.Container, dialog.content)
    assert content.height is None
    assert isinstance(content.content, ft.Column)
    assert content.content.scroll is None


def test_quickreplay_license_view_back_and_close_actions() -> None:
    dialog = _make_dialog()
    controls = _controls(cast(ft.Control, dialog.content))
    license_row = next(
        control
        for control in controls
        if isinstance(control, ft.Row)
        and any(
            isinstance(child, ft.Column) and cast(ft.Text, child.controls[0]).value == "QuickReplay"
            for child in control.controls
        )
    )
    view_button = next(control for control in _buttons(license_row) if control.content == "View")
    _click(view_button)

    assert _title(dialog) == "QuickReplay License"
    content = cast(ft.Container, dialog.content)
    assert content.height is not None
    assert isinstance(content.content, ft.Column)
    assert content.content.scroll == ft.ScrollMode.AUTO
    assert any(
        isinstance(control, ft.Text) and control.value == MIT_LICENSE
        for control in _controls(content)
    )
    assert _action_labels(dialog) == ["Back", "Close"]

    _click(cast(ft.TextButton, dialog.actions[0]))
    assert _title(dialog) == "About"
    assert MIT_LICENSE not in [
        control.value
        for control in _controls(cast(ft.Control, dialog.content))
        if isinstance(control, ft.Text)
    ]


def test_third_party_list_and_local_notice_detail_are_navigable() -> None:
    dialog = _make_dialog()
    top_rows = [
        control
        for control in _controls(cast(ft.Control, dialog.content))
        if isinstance(control, ft.Row)
    ]
    third_party_row = next(
        row
        for row in top_rows
        if any(
            isinstance(control, ft.Text) and control.value == "Third-party licenses"
            for control in row.controls
        )
    )
    top_view = cast(ft.TextButton, third_party_row.controls[1])
    _click(top_view)

    assert _title(dialog) == "Third-party licenses"
    content = cast(ft.Container, dialog.content)
    assert content.height is not None
    assert isinstance(content.content, ft.Column)
    assert content.content.scroll == ft.ScrollMode.AUTO
    rows = [control for control in content.content.controls if isinstance(control, ft.Row)]
    component_names = {
        cast(ft.Text, cast(ft.Column, row.controls[0]).controls[0]).value for row in rows
    }
    assert component_names == {
        "Python",
        "Flet",
        "PyAV",
        "NumPy",
        "ndi-python",
        "NDI SDK / NDI Runtime",
    }

    for row in rows:
        component = cast(ft.Column, row.controls[0])
        assert isinstance(component.controls[1], ft.Text)
        assert cast(ft.TextButton, row.controls[1]).content == "View"
        website = cast(ft.TextButton, row.controls[2])
        assert website.content == "Website"
        assert website.url

    flet_row = next(
        row
        for row in rows
        if cast(ft.Text, cast(ft.Column, row.controls[0]).controls[0]).value == "Flet"
    )
    _click(cast(ft.TextButton, flet_row.controls[1]))
    assert _title(dialog) == "Flet"
    notice_content = cast(ft.Container, dialog.content)
    assert isinstance(notice_content.content, ft.Column)
    assert notice_content.content.scroll == ft.ScrollMode.AUTO
    assert any(
        isinstance(control, ft.Text) and control.value == THIRD_PARTY_NOTICE
        for control in _controls(notice_content)
    )
    assert _action_labels(dialog) == ["Back", "Close"]

    _click(cast(ft.TextButton, dialog.actions[0]))
    assert _title(dialog) == "Third-party licenses"
    _click(cast(ft.TextButton, dialog.actions[0]))
    assert _title(dialog) == "About"


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
