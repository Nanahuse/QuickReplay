"""ApplicationUiBridge: serialization, exception propagation and cleanup."""

import asyncio

import pytest
from fake_ui import FakeController

from quickreplay.input.models import NdiInputConfig
from quickreplay.replay.models import SetPoint
from quickreplay.ui.bridge import ApplicationUiBridge


def test_calls_are_serialized_on_one_thread() -> None:
    controller = FakeController()
    bridge = ApplicationUiBridge(controller)

    async def run() -> None:
        await asyncio.gather(
            bridge.start(),
            bridge.poll(),
            bridge.discover_inputs(),
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


def test_replay_calls_are_delegated_and_serialized() -> None:
    controller = FakeController()
    bridge = ApplicationUiBridge(controller)

    async def run() -> None:
        await asyncio.gather(
            bridge.play(),
            bridge.pause(),
            bridge.is_paused(),
            bridge.step_forward(),
            bridge.step_backward(),
            bridge.seek_frames(20),
            bridge.seek_absolute_ns(1_250_000_000),
            bridge.replay_position_ns(),
            bridge.set_point(),
            bridge.time_difference_ns(SetPoint(0)),
            bridge.frame_difference(SetPoint(0)),
        )
        await bridge.close()

    asyncio.run(run())

    assert len(set(controller.threads)) == 1
    assert controller.max_active == 1
    assert set(controller.calls) == {
        "play",
        "pause",
        "is_paused",
        "step_forward",
        "step_backward",
        "seek_frames",
        "seek_absolute_ns",
        "replay_position_ns",
        "set_point",
        "time_difference_ns",
        "frame_difference",
    }
