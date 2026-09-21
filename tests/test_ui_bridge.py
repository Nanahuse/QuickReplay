"""ApplicationUiBridge: serialization, exception propagation and cleanup."""

import asyncio

import pytest
from fake_ui import FakeController

from quickreplay.input.models import NdiInputConfig
from quickreplay.ui.bridge import ApplicationUiBridge


def test_calls_are_serialized_on_one_thread() -> None:
    controller = FakeController()
    bridge = ApplicationUiBridge(controller)

    async def run() -> None:
        await asyncio.gather(
            bridge.start(),
            bridge.poll(),
            bridge.discover_inputs(camera_backend="dshow"),
            bridge.request_replay(),
            bridge.resume_recording(),
            bridge.snapshot(),
            bridge.shutdown(),
        )
        await bridge.close()

    asyncio.run(run())

    assert len(set(controller.threads)) == 1
    assert controller.max_active == 1
    assert set(controller.calls) == {
        "start",
        "poll",
        "discover_inputs",
        "request_replay",
        "resume_recording",
        "snapshot",
        "shutdown",
    }


def test_exception_propagates_and_executor_survives() -> None:
    controller = FakeController(fail_on="start_recording")
    bridge = ApplicationUiBridge(controller)

    async def run() -> None:
        with pytest.raises(RuntimeError):
            await bridge.start_recording(NdiInputConfig("x"))
        # The executor thread is still usable afterwards.
        await bridge.poll()
        await bridge.close()

    asyncio.run(run())

    assert "poll" in controller.calls


def test_close_is_idempotent() -> None:
    controller = FakeController()
    bridge = ApplicationUiBridge(controller)

    async def run() -> None:
        await bridge.close()
        await bridge.close()

    asyncio.run(run())


def test_start_recording_forwards_config() -> None:
    controller = FakeController()
    bridge = ApplicationUiBridge(controller)

    async def run() -> None:
        await bridge.start_recording(NdiInputConfig("OBS"))
        await bridge.close()

    asyncio.run(run())

    assert controller.calls == ["start_recording"]
