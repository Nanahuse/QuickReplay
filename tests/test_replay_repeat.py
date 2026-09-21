"""Tests for Replay press-and-hold repetition."""

import asyncio

from quickreplay.ui.replay_repeat import ReplayActionRepeater


def test_repeater_runs_sequentially_and_stops_after_cancel() -> None:
    async def scenario() -> None:
        actions: list[str] = []
        gates: list[asyncio.Event] = []

        async def sleep(_seconds: float) -> None:
            gate = asyncio.Event()
            gates.append(gate)
            await gate.wait()

        async def action() -> None:
            actions.append("action")

        repeater = ReplayActionRepeater(sleep=sleep)
        repeater.start(action, delay=0.5, interval=0.085)
        await asyncio.sleep(0)
        assert actions == ["action"]
        assert len(gates) == 1

        gates[0].set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert actions == ["action", "action"]
        assert len(gates) == 2

        await repeater.stop()
        gates[1].set()
        await asyncio.sleep(0)
        assert actions == ["action", "action"]

    asyncio.run(scenario())
