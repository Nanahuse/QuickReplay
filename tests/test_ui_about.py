"""Offline About dialog content and metadata tests."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import cast

import flet as ft
import pytest

from quickreplay.ui import about
from quickreplay.ui.about import GITHUB_URL, MIT_LICENSE, application_version, build_about_dialog


def _controls(control: ft.Control) -> list[ft.Control]:
    result = [control]
    for child in control.controls if isinstance(control, (ft.Column, ft.Row)) else []:
        result.extend(_controls(child))
    if isinstance(control, ft.Container) and control.content is not None:
        result.extend(_controls(control.content))
    return result


def test_about_dialog_shows_project_metadata_and_local_mit_license() -> None:
    dialog = build_about_dialog(lambda _event: None)
    controls = _controls(cast(ft.Control, dialog.content))
    texts = [control.value for control in controls if isinstance(control, ft.Text)]

    assert dialog.modal is True
    assert f"Version {version('quickreplay')}" in texts
    assert "Copyright © 2022 Nanahuse" in texts
    assert any(text == MIT_LICENSE for text in texts)
    assert (
        MIT_LICENSE == (Path(__file__).parents[1] / "LICENSE").read_text(encoding="utf-8").rstrip()
    )
    assert any(
        isinstance(control, ft.TextButton) and control.url == GITHUB_URL for control in controls
    )
    content = cast(ft.Container, dialog.content).content
    assert isinstance(content, ft.Column)
    assert content.scroll == ft.ScrollMode.AUTO


def test_about_dialog_lists_all_required_third_party_licenses() -> None:
    dialog = build_about_dialog(lambda _event: None)
    controls = _controls(cast(ft.Control, dialog.content))
    rows = [control for control in controls if isinstance(control, ft.Row)]
    component_rows = [
        [child for child in row.controls if isinstance(child, (ft.Column, ft.TextButton))]
        for row in rows
    ]
    component_names = {
        cast(ft.Text, row[0].controls[0]).value
        for row in component_rows
        if len(row) == 2 and isinstance(row[0], ft.Column)
    }
    assert component_names == {
        "Python",
        "Flet",
        "PyAV",
        "NumPy",
        "ndi-python",
        "NDI SDK / NDI Runtime",
    }

    license_labels = [
        child.value
        for row in component_rows
        for child in (row[0].controls if len(row) == 2 and isinstance(row[0], ft.Column) else [])
        if isinstance(child, ft.Text)
    ]
    assert "Python Software Foundation License" in license_labels
    assert "Apache License 2.0" in license_labels
    assert license_labels.count("BSD 3-Clause License") == 2
    assert "MIT License" in license_labels
    assert "NDI SDK License" in license_labels
    assert all(
        isinstance(row[1], ft.TextButton) and row[1].url
        for row in component_rows
        if len(row) == 2 and isinstance(row[0], ft.Column)
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
