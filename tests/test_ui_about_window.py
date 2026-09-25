"""Standalone About window Flet entry-point tests."""

import asyncio
import inspect
import os
from typing import Any, cast

import flet as ft

from quickreplay.ui import about_window


class _Window:
    width: int | None = None
    height: int | None = None
    min_width: int | None = None
    min_height: int | None = None
    resizable = False
    maximizable = False
    visible = True

    async def wait_until_ready_to_show(self) -> None:
        pass

    async def destroy(self) -> None:
        pass


class _Page:
    def __init__(self) -> None:
        self.window = _Window()
        self.title = ""
        self.controls: list[ft.Control] = []
        self.tasks: list[tuple[object, tuple[object, ...]]] = []
        self.updates = 0

    def add(self, control: ft.Control) -> None:
        self.controls.append(control)

    def update(self) -> None:
        self.updates += 1

    def run_task(self, handler: object, *args: object) -> None:
        self.tasks.append((handler, args))


def test_about_process_passes_a_coroutine_handler_to_flet(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(main, *, view) -> None:
        captured["main"] = main
        captured["view"] = view

    monkeypatch.setattr(about_window.ft, "run", fake_run)
    shutdown_event = object()

    about_window.run_about_window(shutdown_event)

    main = captured["main"]
    assert inspect.iscoroutinefunction(main)
    assert captured["view"] is ft.AppView.FLET_APP

    page = _Page()
    asyncio.run(main(cast(ft.Page, page)))

    assert page.title == "QuickReplay — About"
    assert (page.window.width, page.window.height) == about_window.ABOUT_WINDOW_SIZE
    assert (page.window.min_width, page.window.min_height) == about_window.ABOUT_WINDOW_MIN_SIZE
    assert page.window.resizable is True
    assert page.window.maximizable is True
    assert page.window.visible is True
    assert page.controls
    assert page.tasks == [(about_window._watch_parent_shutdown, (page, shutdown_event))]


def test_about_process_clears_inherited_flet_runtime_environment(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(main, *, view) -> None:
        captured["main"] = main
        captured["view"] = view

    monkeypatch.setattr(about_window.ft, "run", fake_run)
    monkeypatch.setenv("FLET_PLATFORM", "windows")
    monkeypatch.setenv("FLET_DART_BRIDGE_PORT", "12345")
    monkeypatch.setenv("FLET_FORCE_WEB_SERVER", "true")
    monkeypatch.setenv("FLET_DISPLAY_URL_PREFIX", "http://parent.invalid")
    monkeypatch.setenv("QUICKREPLAY_TEST_VALUE", "preserved")

    about_window.run_about_window(object())

    assert not any(name.startswith("FLET_") for name in os.environ)
    assert os.environ["QUICKREPLAY_TEST_VALUE"] == "preserved"
