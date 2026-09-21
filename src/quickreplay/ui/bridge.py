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

EXECUTOR_THREAD_PREFIX = "QuickReplayApplication"


class ControllerLike(Protocol):
    """The blocking controller operations the bridge forwards."""

    def start(self) -> None: ...

    def start_recording(self, input_config: InputConfig) -> None: ...

    def discover_inputs(self, *, camera_backend: str = "any") -> UUID: ...

    def request_replay(self) -> UUID: ...

    def resume_recording(self) -> UUID: ...

    def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]: ...

    def snapshot(self) -> ApplicationSnapshot: ...

    def shutdown(self) -> None: ...


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

    async def discover_inputs(self, *, camera_backend: str = "any") -> UUID:
        return await self._run(self._controller.discover_inputs, camera_backend=camera_backend)

    async def request_replay(self) -> UUID:
        return await self._run(self._controller.request_replay)

    async def resume_recording(self) -> UUID:
        return await self._run(self._controller.resume_recording)

    async def poll(self, timeout: float = 0.0) -> tuple[ApplicationEvent, ...]:
        return await self._run(self._controller.poll, timeout)

    async def snapshot(self) -> ApplicationSnapshot:
        return await self._run(self._controller.snapshot)

    async def shutdown(self) -> None:
        await self._run(self._controller.shutdown)

    async def close(self) -> None:
        """Shut the executor down.  Call only after :meth:`shutdown`."""
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True)
