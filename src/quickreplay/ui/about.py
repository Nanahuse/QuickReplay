"""Offline About window content for QuickReplay."""

import ctypes
import sys
from ctypes import POINTER, Structure, byref, c_void_p, cast, create_string_buffer
from importlib.metadata import PackageNotFoundError, version

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


def build_about_ui(page: ft.Page) -> ft.Control:
    """Build the standalone About window body with local license views."""
    content = ft.Container(expand=True)

    def show_quickreplay_license(_event: ft.Event | None = None) -> None:
        content.content = ft.Column(
            controls=[
                ft.Text("QuickReplay License", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(MIT_LICENSE, selectable=True),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        page.update()

    def show_third_party_notices(_event: ft.Event | None = None) -> None:
        content.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Third-party notices", size=18, weight=ft.FontWeight.BOLD),
                        ft.TextButton(
                            content="Back to licenses", on_click=show_third_party_licenses
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Text(THIRD_PARTY_NOTICE, selectable=True, expand=True),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        page.update()

    def show_third_party_licenses(_event: ft.Event | None = None) -> None:
        rows = [
            ft.Row(
                controls=[
                    ft.Column(
                        controls=[ft.Text(name, weight=ft.FontWeight.BOLD), ft.Text(license_name)],
                        spacing=0,
                        expand=True,
                    ),
                    ft.TextButton(content="Website", url=url),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            for name, license_name, url in THIRD_PARTY_LICENSES
        ]
        content.content = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Third-party Licenses", size=18, weight=ft.FontWeight.BOLD),
                        ft.TextButton(
                            content="View third-party notices",
                            on_click=show_third_party_notices,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                *rows,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        page.update()

    content.content = ft.Column(
        controls=[
            ft.Text("QuickReplay License", size=18, weight=ft.FontWeight.BOLD),
            ft.Text(MIT_LICENSE, selectable=True),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text("QuickReplay", size=26, weight=ft.FontWeight.BOLD),
                            ft.Text(f"Version {application_version()} · © 2022 Nanahuse"),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.TextButton(content="GitHub", url=GITHUB_URL),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Divider(),
            ft.Row(
                controls=[
                    ft.OutlinedButton(
                        content="QuickReplay License", on_click=show_quickreplay_license
                    ),
                    ft.OutlinedButton(
                        content="Third-party Licenses", on_click=show_third_party_licenses
                    ),
                ],
                spacing=8,
            ),
            content,
        ],
        spacing=8,
        expand=True,
    )
