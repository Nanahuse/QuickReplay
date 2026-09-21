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
from quickreplay.ui.main_view import MainView, is_destroyed_session_error
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


def _show_startup_error(page: ft.Page, message: str) -> None:
    """Render a startup error, tolerating an already destroyed Flet session."""
    try:
        page.add(_startup_error(message))
        page.update()
    except RuntimeError as exc:
        if not is_destroyed_session_error(exc):
            raise


async def main(page: ft.Page) -> None:
    """Flet entry point."""
    page.title = "QuickReplay"
    page.window.width = 900
    page.window.height = 720

    try:
        paths = storage_paths_from_environment()
        bootstrap = bootstrap_application(paths=paths)
    except StoragePathError as exc:
        _show_startup_error(page, str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - show configuration/startup errors in the UI
        _show_startup_error(page, str(exc))
        return

    session = UiSession(bootstrap.bridge, bootstrap.store, bootstrap.config)
    view = MainView(page, session)
    page.add(view.control)
    page.window.prevent_close = True
    page.window.on_event = view.on_window_event
    page.on_disconnect = view.on_page_disconnect

    try:
        await view.start()
    except Exception as exc:  # noqa: BLE001 - view.start already cleaned the core up
        _show_startup_error(page, f"Could not start the application: {exc}")
        return

    if view.is_active:
        view.start_polling()


def run() -> None:
    """Start the Flet desktop application."""
    ft.run(main)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run()
