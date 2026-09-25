"""Offline About dialog content for QuickReplay."""

import ctypes
import sys
from ctypes import POINTER, Structure, byref, c_void_p, cast, create_string_buffer
from importlib.metadata import PackageNotFoundError, version

import flet as ft

GITHUB_URL = "https://github.com/Nanahuse/QuickReplay"

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


def _third_party_row(name: str, license_name: str, url: str) -> ft.Row:
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
            ft.TextButton(content="License info", url=url),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def build_about_dialog(on_close) -> ft.AlertDialog:
    """Build a self-contained, scrollable About dialog with offline license text."""
    licenses = [
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
    ]
    content = ft.Container(
        width=520,
        height=520,
        content=ft.Column(
            controls=[
                ft.Text("QuickReplay", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(f"Version {application_version()}"),
                ft.Text("Copyright © 2022 Nanahuse"),
                ft.TextButton(content="GitHub", url=GITHUB_URL),
                ft.Divider(),
                ft.Text("QuickReplay License", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(MIT_LICENSE, selectable=True),
                ft.Divider(),
                ft.Text("Third-party licenses", size=18, weight=ft.FontWeight.BOLD),
                *(_third_party_row(*license_info) for license_info in licenses),
                ft.Text(
                    "The portable Windows package also includes LICENSE_ThirdParty.md.",
                    size=12,
                    color=ft.Colors.BLUE_GREY,
                ),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=12,
    )
    return ft.AlertDialog(
        modal=True,
        title=ft.Text("About"),
        content=content,
        actions=[ft.TextButton(content="Close", on_click=on_close)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
