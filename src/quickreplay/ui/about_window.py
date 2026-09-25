"""Standalone Flet window process for QuickReplay About and license information."""

import asyncio
import os
from typing import Any

import flet as ft

from quickreplay.ui.about import build_about_ui

ABOUT_WINDOW_SIZE = (680, 540)
ABOUT_WINDOW_MIN_SIZE = (560, 400)


async def about_page(page: ft.Page, shutdown_event: Any) -> None:
    """Configure the standalone About window and watch for parent shutdown."""
    page.title = "QuickReplay — About"
    page.window.width, page.window.height = ABOUT_WINDOW_SIZE
    page.window.min_width, page.window.min_height = ABOUT_WINDOW_MIN_SIZE
    page.window.resizable = True
    page.window.maximizable = True
    page.window.visible = False
    page.add(ft.Container(content=build_about_ui(page), expand=True, padding=16))
    await page.window.wait_until_ready_to_show()
    page.window.visible = True
    page.update()
    page.run_task(_watch_parent_shutdown, page, shutdown_event)


async def _watch_parent_shutdown(page: ft.Page, shutdown_event: Any) -> None:
    while not shutdown_event.is_set():
        await asyncio.sleep(0.1)
    try:
        await page.window.destroy()
    except RuntimeError:
        # The user may close About between the event check and window destroy.
        return


def run_about_window(shutdown_event: Any) -> None:
    """Pickleable multiprocessing entry point for the native About window."""
    # Serious Python sets these in the main embedded app. A spawned helper must
    # not attach its Flet page to the parent's Dart bridge instead of opening a
    # standalone native window.
    os.environ.pop("FLET_PLATFORM", None)
    os.environ.pop("FLET_DART_BRIDGE_PORT", None)

    async def main(page: ft.Page) -> None:
        await about_page(page, shutdown_event)

    ft.run(main, view=ft.AppView.FLET_APP)
