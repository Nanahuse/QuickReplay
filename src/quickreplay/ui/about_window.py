"""Standalone Flet window process for QuickReplay About and license information."""

import os

import flet as ft

from quickreplay.ui.about import build_about_ui

ABOUT_WINDOW_SIZE = (680, 540)
ABOUT_WINDOW_MIN_SIZE = (560, 400)


async def about_page(page: ft.Page) -> None:
    """Configure the standalone About window."""
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


def run_about_window(*, embedded: bool) -> None:
    """Run About in a dedicated app process or a standalone development view."""
    if not embedded:
        # A development subprocess should create its own desktop client instead
        # of attaching to the Flet runner's embedded bridge.
        for name in tuple(os.environ):
            if name.startswith("FLET_"):
                os.environ.pop(name, None)

    async def main(page: ft.Page) -> None:
        await about_page(page)

    ft.run(main, view=ft.AppView.FLET_APP)


def run_about_from_command_line() -> None:
    """Entry point used by a separately launched packaged app instance."""
    run_about_window(embedded=True)


if __name__ == "__main__":
    # ``python -m quickreplay.ui.about_window`` development entry point.
    run_about_window(embedded=False)
