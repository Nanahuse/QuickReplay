"""MainView lifecycle: poll ownership, close idempotency and race guards.

Everything runs headlessly with a stub page and fake bridge, so no native Flet
window is created.
"""

import asyncio
import threading
from pathlib import Path
from typing import cast

import flet as ft
import pytest
from fake_ui import FakeBridge

from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.ui.main_view import MainView, ViewLifecycle
from quickreplay.ui.session import UiSession

DESTROYED_SESSION = "An attempt to fetch destroyed session."


class _Event:
    """A stand-in for a Flet event object."""


class _CloseEvent:
    type = ft.WindowEventType.CLOSE


def _event() -> ft.Event:
    return cast(ft.Event, _Event())


def _close_event() -> ft.WindowEvent:
    return cast(ft.WindowEvent, _CloseEvent())


class LifecyclePage:
    """The slice of :class:`flet.Page` used by MainView, with failure injection."""

    def __init__(
        self,
        *,
        update_error: BaseException | None = None,
        run_task_error: BaseException | None = None,
    ) -> None:
        self.updates = 0
        self.dialogs: list[object] = []
        self.destroyed = 0
        self.update_error = update_error
        self.run_task_error = run_task_error
        self.tasks: list[asyncio.Task[object]] = []
        self.window = self

    def update(self) -> None:
        if self.update_error is not None:
            raise self.update_error
        self.updates += 1

    def show_dialog(self, dialog: object) -> None:
        self.dialogs.append(dialog)

    def pop_dialog(self) -> object | None:
        return self.dialogs.pop() if self.dialogs else None

    def run_task(self, handler, *args, **kwargs):
        if self.run_task_error is not None:
            raise self.run_task_error
        task = asyncio.ensure_future(handler(*args, **kwargs))
        self.tasks.append(task)
        return task

    async def destroy(self) -> None:
        self.destroyed += 1


class CountingBridge(FakeBridge):
    """FakeBridge that counts shutdown/close calls and records their order."""

    def __init__(self) -> None:
        super().__init__()
        self.shutdown_count = 0
        self.close_count = 0
        self.order: list[str] = []

    async def shutdown(self) -> None:
        self.shutdown_count += 1
        self.order.append("shutdown")
        await super().shutdown()

    async def close(self) -> None:
        self.close_count += 1
        self.order.append("close")
        await super().close()


class BlockingBridge(CountingBridge):
    """Bridge whose operations can be blocked deterministically."""

    def __init__(self) -> None:
        super().__init__()
        self.poll_entered = asyncio.Event()
        self.poll_release = asyncio.Event()
        self.start_entered = asyncio.Event()
        self.start_release = asyncio.Event()
        self.discover_entered = asyncio.Event()
        self.discover_release = asyncio.Event()
        self.step_entered = asyncio.Event()
        self.step_release = asyncio.Event()

    async def poll(self, timeout: float = 0.0):
        self.poll_entered.set()
        await self.poll_release.wait()
        return ()

    async def start(self) -> None:
        self.start_entered.set()
        await self.start_release.wait()
        self.started = True

    async def discover_inputs(self, *, camera_backend: str = "any"):
        self.discover_entered.set()
        await self.discover_release.wait()
        return await super().discover_inputs(camera_backend=camera_backend)

    async def step_forward(self) -> None:
        self.step_entered.set()
        await self.step_release.wait()
        await super().step_forward()


class BlockingStore(ConfigurationStore):
    """Store whose save can be blocked from the test thread."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.entered = threading.Event()
        self.release = threading.Event()

    def save(self, config: QuickReplayConfig) -> None:
        self.entered.set()
        self.release.wait(timeout=10)
        super().save(config)


async def _wait_for(predicate, *, attempts: int = 200) -> None:
    """Yield to the event loop until *predicate* holds (bounded)."""
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not met")


def _make(
    tmp_path: Path,
    *,
    bridge: FakeBridge | None = None,
    page: LifecyclePage | None = None,
    store: ConfigurationStore | None = None,
) -> tuple[MainView, UiSession, CountingBridge, LifecyclePage]:
    active_bridge = bridge or CountingBridge()
    active_store = store or ConfigurationStore(tmp_path / "config.json")
    session = UiSession(active_bridge, active_store, QuickReplayConfig())
    active_page = page or LifecyclePage()
    view = MainView(cast(ft.Page, active_page), session)
    assert isinstance(active_bridge, CountingBridge)
    return view, session, active_bridge, active_page


# -- poll task ownership ---------------------------------------------------


def test_start_polling_stores_task_and_close_cancels_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        view, _session, bridge, page = _make(tmp_path)
        await view.start()
        view.start_polling()
        await asyncio.sleep(0)

        assert view._poll_task is not None
        assert not view._poll_task.done()

        await view.close()

        assert view.lifecycle is ViewLifecycle.CLOSED
        assert view._poll_task is None
        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1
        assert page.destroyed == 1

    asyncio.run(scenario())


def test_poll_cancellation_is_not_reported_as_an_error(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = BlockingBridge()
        view, session, _bridge, page = _make(tmp_path, bridge=bridge)
        view.start_polling()
        await bridge.poll_entered.wait()
        updates_before = page.updates

        await view.close()

        assert view.lifecycle is ViewLifecycle.CLOSED
        assert page.updates == updates_before
        assert session.view_state().error_message is None

    asyncio.run(scenario())


def test_poll_loop_stops_on_close_without_further_updates(tmp_path: Path) -> None:
    async def scenario() -> None:
        view, _session, _bridge, page = _make(tmp_path)
        view.start_polling()
        await asyncio.sleep(0)
        await view.close()
        updates_after_close = page.updates

        await asyncio.sleep(0.05)

        assert page.updates == updates_after_close
        assert view._poll_task is None

    asyncio.run(scenario())


# -- destroyed session -----------------------------------------------------


def test_destroyed_session_runs_core_cleanup(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = LifecyclePage(update_error=RuntimeError(DESTROYED_SESSION))
        view, session, bridge, _page = _make(tmp_path, page=page)
        view.start_polling()
        await _wait_for(lambda: view.lifecycle is ViewLifecycle.CLOSED)

        assert view._session_lost
        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1
        assert page.destroyed == 0
        assert session.view_state().error_message is None

    asyncio.run(scenario())


def test_destroyed_session_is_not_an_application_error(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = LifecyclePage(update_error=RuntimeError(DESTROYED_SESSION))
        view, session, _bridge, _page = _make(tmp_path, page=page)

        assert view._update_page() is False

        assert view._session_lost
        assert session.view_state().error_message is None

    asyncio.run(scenario())


def test_unrelated_runtime_error_is_not_swallowed(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = LifecyclePage(update_error=RuntimeError("render failed"))
        view, _session, _bridge, _page = _make(tmp_path, page=page)

        with pytest.raises(RuntimeError, match="render failed"):
            view._update_page()

        assert not view._session_lost
        assert view.lifecycle is ViewLifecycle.RUNNING

    asyncio.run(scenario())


def test_unrelated_runtime_error_propagates_from_action_refresh(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = LifecyclePage(update_error=RuntimeError("render failed"))
        view, _session, _bridge, _page = _make(tmp_path, page=page)

        with pytest.raises(RuntimeError, match="render failed"):
            await view._render_and_update()

    asyncio.run(scenario())


# -- close idempotency -----------------------------------------------------


def test_double_close_runs_shutdown_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        view, _session, bridge, page = _make(tmp_path)

        await view.close()
        await view.close()

        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1
        assert page.destroyed == 1

    asyncio.run(scenario())


def test_concurrent_close_runs_shutdown_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        view, _session, bridge, page = _make(tmp_path)

        await asyncio.gather(view.close(), view.close())

        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1
        assert page.destroyed == 1

    asyncio.run(scenario())


def test_window_close_and_disconnect_run_shutdown_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        view, _session, bridge, _page = _make(tmp_path)

        view.on_window_event(_close_event())
        view.on_page_disconnect()
        await _wait_for(lambda: view.lifecycle is ViewLifecycle.CLOSED)

        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1

    asyncio.run(scenario())


def test_run_task_failure_during_close_falls_back_to_cleanup(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = LifecyclePage(run_task_error=RuntimeError(DESTROYED_SESSION))
        view, _session, bridge, _page = _make(tmp_path, page=page)

        view.on_window_event(_close_event())
        await _wait_for(lambda: view.lifecycle is ViewLifecycle.CLOSED)

        assert bridge.shutdown_count == 1
        assert page.destroyed == 0

    asyncio.run(scenario())


# -- action guards ---------------------------------------------------------


def test_actions_after_close_do_not_call_core(tmp_path: Path) -> None:
    async def scenario() -> None:
        view, _session, bridge, page = _make(tmp_path)
        await view.close()
        updates_after_close = page.updates

        view._on_start(_event())
        view._on_refresh(_event())
        view._on_replay(_event())
        view._on_resume(_event())
        view._run_replay_action("step_forward")
        view._on_settings_apply(_event())
        view._on_settings_open(_event())
        view._on_settings_cancel(_event())
        view._on_source_select(_event())
        view._on_seek_start(_event())
        view._on_seek_change(_event())
        view._on_seek_end(_event())
        await asyncio.sleep(0)

        assert bridge.recording_configs == []
        assert bridge.discovery_requests == []
        assert bridge.replay_requests == 0
        assert bridge.resume_requests == 0
        assert bridge.step_forward_calls == 0
        assert bridge.seek_absolute_calls == []
        assert page.updates == updates_after_close
        assert page.dialogs == []

    asyncio.run(scenario())


def test_action_completion_after_close_does_not_update_page(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = BlockingBridge()
        view, _session, _bridge, page = _make(tmp_path, bridge=bridge)

        task = asyncio.ensure_future(view._refresh())
        await bridge.discover_entered.wait()
        updates_before = page.updates

        await view.close()
        bridge.discover_release.set()
        await task

        assert page.updates == updates_before
        assert view.lifecycle is ViewLifecycle.CLOSED

    asyncio.run(scenario())


def test_replay_action_completion_after_close_does_not_update_page(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = BlockingBridge()
        view, _session, _bridge, page = _make(tmp_path, bridge=bridge)

        task = asyncio.ensure_future(view._do_replay_action("step_forward", None))
        await bridge.step_entered.wait()
        updates_before = page.updates

        await view.close()
        bridge.step_release.set()
        await task

        assert page.updates == updates_before
        assert view.lifecycle is ViewLifecycle.CLOSED

    asyncio.run(scenario())


def test_settings_apply_race_does_not_touch_the_page(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = BlockingStore(tmp_path / "config.json")
        view, _session, _bridge, page = _make(tmp_path, store=store)
        view._on_settings_open(_event())

        task = asyncio.ensure_future(view._apply_settings())
        await asyncio.to_thread(store.entered.wait)
        updates_before = page.updates

        await view.close()
        store.release.set()
        await task

        assert page.updates == updates_before
        # The dialog was never closed and the draft was never applied.
        assert page.dialogs == [view.settings_dialog]
        assert view.settings_error_text.value == ""

    asyncio.run(scenario())


def test_seek_drag_close_does_not_send_seek(tmp_path: Path) -> None:
    async def scenario() -> None:
        view, _session, bridge, _page = _make(tmp_path)
        view._on_seek_start(_event())
        assert view._seek_drag.active

        await view.close()
        view._on_seek_end(_event())
        await asyncio.sleep(0)

        assert bridge.seek_absolute_calls == []

    asyncio.run(scenario())


# -- startup ---------------------------------------------------------------


def test_close_during_start_does_not_start_polling(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = BlockingBridge()
        bridge.discover_release.set()
        view, _session, _bridge, page = _make(tmp_path, bridge=bridge)

        task = asyncio.ensure_future(view.start())
        await bridge.start_entered.wait()

        view.on_window_event(_close_event())
        await asyncio.sleep(0)
        bridge.start_release.set()
        await task
        await _wait_for(lambda: view.lifecycle is ViewLifecycle.CLOSED)

        assert not view.is_active

        view.start_polling()
        assert view._poll_task is None

        assert bridge.shutdown_count == 1
        assert page.destroyed == 1

    asyncio.run(scenario())


def test_start_failure_cleans_up_core(tmp_path: Path) -> None:
    class FailingStartBridge(CountingBridge):
        async def start(self) -> None:
            raise RuntimeError("worker spawn failed")

    async def scenario() -> None:
        bridge = FailingStartBridge()
        view, _session, _bridge, page = _make(tmp_path, bridge=bridge)

        with pytest.raises(RuntimeError, match="worker spawn failed"):
            await view.start()

        assert view.lifecycle is ViewLifecycle.CLOSED
        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1
        assert page.destroyed == 0

    asyncio.run(scenario())


# -- state-specific close --------------------------------------------------


# -- UiSession shutdown idempotency ---------------------------------------


def test_session_shutdown_is_idempotent(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = CountingBridge()
        session = UiSession(
            bridge, ConfigurationStore(tmp_path / "config.json"), QuickReplayConfig()
        )

        await session.shutdown()
        await session.shutdown()

        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1

    asyncio.run(scenario())


def test_session_shutdown_is_concurrency_safe(tmp_path: Path) -> None:
    async def scenario() -> None:
        bridge = CountingBridge()
        session = UiSession(
            bridge, ConfigurationStore(tmp_path / "config.json"), QuickReplayConfig()
        )

        await asyncio.gather(session.shutdown(), session.shutdown())

        assert bridge.shutdown_count == 1
        assert bridge.close_count == 1

    asyncio.run(scenario())
