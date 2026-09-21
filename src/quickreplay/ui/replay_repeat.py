"""Async press-and-hold repetition for Replay frame actions."""

import asyncio
from collections.abc import Awaitable, Callable

Action = Callable[[], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]


class ReplayActionRepeater:
    """Run one action immediately, then sequentially while the press is held."""

    def __init__(self, *, sleep: Sleep = asyncio.sleep) -> None:
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._held = False

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, action: Action, *, delay: float, interval: float) -> None:
        self.release()
        self._held = True
        self._task = asyncio.create_task(self._run(action, delay=delay, interval=interval))

    def release(self) -> None:
        """Stop future repetitions without interrupting the current action."""
        self._held = False

    def cancel(self) -> None:
        """Cancel the task immediately for backwards-compatible shutdown use."""
        self._held = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def stop(self) -> None:
        task = self._task
        self._task = None
        self._held = False
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self, action: Action, *, delay: float, interval: float) -> None:
        await action()
        if not self._held:
            return
        await self._sleep(delay)
        while self._held:
            await action()
            if not self._held:
                return
            await self._sleep(interval)
