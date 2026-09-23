"""Async boundary between the Flet event loop and the blocking application core.

Every :class:`~quickreplay.application.controller.ApplicationController` call
runs on a dedicated single-worker executor, so the asyncio loop is never
blocked and controller calls are serialized (never two at once).
"""

import asyncio
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol
from uuid import UUID

from quickreplay.application.events import ApplicationEvent
from quickreplay.application.models import ApplicationSnapshot
from quickreplay.input.models import InputConfig
from quickreplay.replay.models import SetPoint

EXECUTOR_THREAD_PREFIX = "QuickReplayApplication"


class ControllerLike(Protocol):
    """The blocking controller operations the bridge forwards."""

    def start(self) -> None: ...

    def start_recording(self, input_config: InputConfig) -> None: ...

    def discover_inputs(self) -> UUID: ...

    def request_replay(self) -> UUID: ...

    def resume_recording(self) -> UUID: ...

    def stop_session(self) -> UUID: ...

    def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]: ...

    def snapshot(self) -> ApplicationSnapshot: ...

    def shutdown(self) -> None: ...

    # -- replay delegate ---------------------------------------------------
    def play(self) -> None: ...

    def pause(self) -> None: ...

    def is_paused(self) -> bool: ...

    def step_forward(self) -> None: ...

    def step_backward(self) -> None: ...

    def seek_frames(self, frames: int) -> None: ...

    def seek_absolute_ns(self, position_ns: int) -> None: ...

    def replay_position_ns(self) -> int: ...

    def set_point(self) -> SetPoint: ...

    def time_difference_ns(self, point: SetPoint) -> int: ...

    def frame_difference(self, point: SetPoint) -> int: ...


class ApplicationUiBridge:
    """Serializes blocking controller calls onto one worker thread."""

    def __init__(
        self,
        controller: ControllerLike,
        *,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._controller = controller
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=EXECUTOR_THREAD_PREFIX
        )
        self._closed = False

    async def _run[T](self, func: Callable[..., T], *args, **kwargs) -> T:
        loop = asyncio.get_running_loop()
        call = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(self._executor, call)

    async def start(self) -> None:
        await self._run(self._controller.start)

    async def start_recording(self, input_config: InputConfig) -> None:
        await self._run(self._controller.start_recording, input_config)

    async def discover_inputs(self) -> UUID:
        return await self._run(self._controller.discover_inputs)

    async def request_replay(self) -> UUID:
        return await self._run(self._controller.request_replay)

    async def resume_recording(self) -> UUID:
        return await self._run(self._controller.resume_recording)

    async def stop_session(self) -> UUID:
        return await self._run(self._controller.stop_session)

    async def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]:
        return await self._run(self._controller.poll, timeout)

    async def snapshot(self) -> ApplicationSnapshot:
        return await self._run(self._controller.snapshot)

    async def shutdown(self) -> None:
        await self._run(self._controller.shutdown)

    # -- replay delegate ---------------------------------------------------
    async def play(self) -> None:
        await self._run(self._controller.play)

    async def pause(self) -> None:
        await self._run(self._controller.pause)

    async def is_paused(self) -> bool:
        return await self._run(self._controller.is_paused)

    async def step_forward(self) -> None:
        await self._run(self._controller.step_forward)

    async def step_backward(self) -> None:
        await self._run(self._controller.step_backward)

    async def seek_frames(self, frames: int) -> None:
        await self._run(self._controller.seek_frames, frames)

    async def seek_absolute_ns(self, position_ns: int) -> None:
        await self._run(self._controller.seek_absolute_ns, position_ns)

    async def replay_position_ns(self) -> int:
        return await self._run(self._controller.replay_position_ns)

    async def set_point(self) -> SetPoint:
        return await self._run(self._controller.set_point)

    async def time_difference_ns(self, point: SetPoint) -> int:
        return await self._run(self._controller.time_difference_ns, point)

    async def frame_difference(self, point: SetPoint) -> int:
        return await self._run(self._controller.frame_difference, point)

    async def close(self) -> None:
        """Shut the executor down.  Call only after :meth:`shutdown`."""
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True)
