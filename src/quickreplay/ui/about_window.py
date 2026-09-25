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
    # A spawned helper must not inherit the main app's embedded bridge, web
    # server, or display-routing configuration. Those settings can leave the
    # child serving a page with no native window, or attach it to the parent.
    for name in tuple(os.environ):
        if name.startswith("FLET_"):
            os.environ.pop(name, None)

    async def main(page: ft.Page) -> None:
        await about_page(page, shutdown_event)

    ft.run(main, view=ft.AppView.FLET_APP)
