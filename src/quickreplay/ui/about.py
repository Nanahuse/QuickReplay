"""Offline About dialog content for QuickReplay."""

import ctypes
import sys
from collections.abc import Callable
from ctypes import POINTER, Structure, byref, c_void_p, cast, create_string_buffer
from importlib.metadata import PackageNotFoundError, version
from typing import cast as typing_cast

import flet as ft

GITHUB_URL = "https://github.com/Nanahuse/QuickReplay"
THIRD_PARTY_NOTICE = """# Third-party notices

This file lists the primary third-party components used by the QuickReplay
Version 2 runtime and Windows package.

## Python

Python Software Foundation License<br>
https://docs.python.org/3/license.html#psf-license

## Flet

Apache License 2.0<br>
https://github.com/flet-dev/flet/blob/main/LICENSE

## PyAV

BSD 3-Clause License<br>
https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt

## NumPy

BSD 3-Clause License<br>
https://github.com/numpy/numpy/blob/main/LICENSE.txt

## ndi-python

MIT License<br>
https://github.com/buresu/ndi-python/blob/master/LICENSE

## NDI SDK / NDI runtime

NDI SDK License<br>
https://ndi.video/for-developers/ndi-sdk/license/

QuickReplay does not bundle mpv. Replay playback uses the external mpv
executable configured by the user."""

THIRD_PARTY_LICENSES = (
    (
        "Python",
        "Python Software Foundation License",
        "https://docs.python.org/3/license.html#psf-license",
    ),
    ("Flet", "Apache License 2.0", "https://github.com/flet-dev/flet/blob/main/LICENSE"),
    ("PyAV", "BSD 3-Clause License", "https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt"),
    ("NumPy", "BSD 3-Clause License", "https://github.com/numpy/numpy/blob/main/LICENSE.txt"),
    ("ndi-python", "MIT License", "https://github.com/buresu/ndi-python/blob/master/LICENSE"),
    (
        "NDI SDK / NDI Runtime",
        "NDI SDK License",
        "https://ndi.video/for-developers/ndi-sdk/license/",
    ),
)

MIT_LICENSE = """MIT License

Copyright (c) 2022 Nanahuse

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""


def application_version() -> str:
    """Read the project version from package metadata or the packaged Windows executable."""
    try:
        return version("quickreplay")
    except PackageNotFoundError:
        return _windows_executable_version() or "Unknown"


def _windows_executable_version() -> str | None:
    """Read the ProductVersion embedded by Flet from the Windows executable."""
    if sys.platform != "win32":
        return None

    class FixedFileInfo(Structure):
        _fields_ = [
            ("signature", ctypes.c_uint32),
            ("structure_version", ctypes.c_uint32),
            ("file_version_ms", ctypes.c_uint32),
            ("file_version_ls", ctypes.c_uint32),
            ("product_version_ms", ctypes.c_uint32),
            ("product_version_ls", ctypes.c_uint32),
            ("flags_mask", ctypes.c_uint32),
            ("flags", ctypes.c_uint32),
            ("file_os", ctypes.c_uint32),
            ("file_type", ctypes.c_uint32),
            ("file_subtype", ctypes.c_uint32),
            ("file_date_ms", ctypes.c_uint32),
            ("file_date_ls", ctypes.c_uint32),
        ]

    library = ctypes.WinDLL("version", use_last_error=True)
    for executable in dict.fromkeys((sys.argv[0], sys.executable)):
        if not executable:
            continue
        ignored_handle = ctypes.c_uint32()
        size = library.GetFileVersionInfoSizeW(executable, byref(ignored_handle))
        if not size:
            continue

        data = create_string_buffer(size)
        if not library.GetFileVersionInfoW(executable, 0, size, data):
            continue

        value = c_void_p()
        value_length = ctypes.c_uint32()
        if not library.VerQueryValueW(data, "\\", byref(value), byref(value_length)):
            continue

        info = cast(value, POINTER(FixedFileInfo)).contents
        major, minor = info.product_version_ms >> 16, info.product_version_ms & 0xFFFF
        patch, build = info.product_version_ls >> 16, info.product_version_ls & 0xFFFF
        version_text = f"{major}.{minor}.{patch}"
        return f"{version_text}.{build}" if build else version_text
    return None


def _third_party_row(
    name: str,
    license_name: str,
    url: str,
    on_view: Callable[[ft.Event], None],
) -> ft.Row:
    return ft.Row(
        controls=[
            ft.Column(
                controls=[
                    ft.Text(name, weight=ft.FontWeight.BOLD),
                    ft.Text(license_name),
                ],
                spacing=0,
                expand=True,
            ),
            ft.TextButton(content="View", on_click=on_view),
            ft.TextButton(content="Website", url=url),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def build_about_dialog(
    on_close: Callable[[ft.Event], None], on_update: Callable[[], None]
) -> ft.AlertDialog:
    """Build the compact About dialog and its internal license views."""
    dialog = ft.AlertDialog(modal=True)

    def show_top(_event: ft.Event | None = None, *, notify: bool = True) -> None:
        dialog.title = ft.Text("About")
        dialog.content = ft.Container(
            width=480,
            padding=8,
            content=ft.Column(
                controls=[
                    ft.Text("QuickReplay", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Version {application_version()}"),
                    ft.Text("Copyright © 2022 Nanahuse"),
                    ft.TextButton(content="GitHub", url=GITHUB_URL),
                    ft.Divider(),
                    ft.Text("Licenses", size=18, weight=ft.FontWeight.BOLD),
                    ft.Row(
                        controls=[
                            ft.Column(
                                controls=[ft.Text("QuickReplay"), ft.Text("MIT License")],
                                spacing=0,
                                expand=True,
                            ),
                            ft.TextButton(content="View", on_click=show_mit_license),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text("Third-party licenses", expand=True),
                            ft.TextButton(content="View", on_click=show_third_party_list),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=3,
                tight=True,
            ),
        )
        dialog.actions = [ft.TextButton(content="Close", on_click=on_close)]
        if notify:
            on_update()

    def show_mit_license(_event: ft.Event | None = None) -> None:
        dialog.title = ft.Text("QuickReplay License")
        dialog.content = ft.Container(
            width=480,
            height=190,
            padding=8,
            content=ft.Column(
                controls=[ft.Text(MIT_LICENSE, selectable=True)],
                scroll=ft.ScrollMode.AUTO,
            ),
        )
        dialog.actions = [
            ft.TextButton(content="Back", on_click=show_top),
            ft.TextButton(content="Close", on_click=on_close),
        ]
        on_update()

    def show_third_party_notice(
        _event: ft.Event | None = None,
        component: str | None = None,
        license_name: str | None = None,
    ) -> None:
        dialog.title = ft.Text(component or "Third-party licenses")
        dialog.content = ft.Container(
            width=480,
            height=190,
            padding=8,
            content=ft.Column(
                controls=[
                    *(
                        [
                            ft.Text(license_name or "", weight=ft.FontWeight.BOLD),
                            ft.Divider(),
                        ]
                        if component
                        else []
                    ),
                    ft.Text(THIRD_PARTY_NOTICE, selectable=True),
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
        )
        dialog.actions = [
            ft.TextButton(content="Back", on_click=show_third_party_list),
            ft.TextButton(content="Close", on_click=on_close),
        ]
        on_update()

    def show_third_party_list(_event: ft.Event | None = None) -> None:
        dialog.title = ft.Text("Third-party licenses")
        rows = [
            _third_party_row(
                name,
                license_name,
                url,
                lambda event, name=name, license_name=license_name: show_third_party_notice(
                    event, name, license_name
                ),
            )
            for name, license_name, url in THIRD_PARTY_LICENSES
        ]
        dialog.content = ft.Container(
            width=480,
            height=205,
            padding=8,
            content=ft.Column(
                controls=typing_cast(list[ft.Control], rows),
                spacing=2,
                scroll=ft.ScrollMode.AUTO,
            ),
        )
        dialog.actions = [
            ft.TextButton(content="Back", on_click=show_top),
            ft.TextButton(content="Close", on_click=on_close),
        ]
        on_update()

    show_top(notify=False)
    return dialog
