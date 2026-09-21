"""Flet desktop entry point.

Run with::

    uv run flet run src/quickreplay/ui/app.py

The application is not started on import; only ``run`` (under the
``__main__`` guard) starts it, together with ``multiprocessing.freeze_support``
for the spawned recorder worker process.
"""

import multiprocessing

import flet as ft

from quickreplay.ui.bootstrap import bootstrap_application
from quickreplay.ui.main_view import MainView
from quickreplay.ui.paths import StoragePathError, storage_paths_from_environment
from quickreplay.ui.session import UiSession


def _startup_error(message: str) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("QuickReplay", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Startup failed", color=ft.Colors.RED, weight=ft.FontWeight.BOLD),
            ft.Text(message),
        ],
        spacing=10,
    )


async def main(page: ft.Page) -> None:
    """Flet entry point."""
    page.title = "QuickReplay"
    page.window.width = 900
    page.window.height = 720

    try:
        paths = storage_paths_from_environment()
        bootstrap = bootstrap_application(paths=paths)
    except StoragePathError as exc:
        page.add(_startup_error(str(exc)))
        page.update()
        return
    except Exception as exc:  # noqa: BLE001 - show configuration/startup errors in the UI
        page.add(_startup_error(str(exc)))
        page.update()
        return

    session = UiSession(bootstrap.bridge, bootstrap.store, bootstrap.config)
    view = MainView(page, session)
    page.add(view.control)
    page.window.prevent_close = True
    page.window.on_event = view.on_window_event
    page.run_task(view.poll_loop)
    await view.start()


def run() -> None:
    """Start the Flet desktop application."""
    ft.run(main)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run()
