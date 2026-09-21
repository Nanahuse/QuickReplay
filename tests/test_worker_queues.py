"""FrameQueues: drop-oldest, hold-back gating and cross-stream ordering."""

from fractions import Fraction

import numpy as np

from quickreplay.input.models import AudioFrame, VideoFrame
from quickreplay.worker.frame_queues import FrameQueues

FPS = Fraction(60, 1)


def _video(timestamp_ns: int) -> VideoFrame:
    return VideoFrame(timestamp_ns, 4, 2, FPS, "BGR24", np.zeros((2, 4, 3), dtype=np.uint8))


def _audio(timestamp_ns: int, samples: int = 10) -> AudioFrame:
    return AudioFrame(timestamp_ns, 48000, 2, samples, np.zeros((2, samples), dtype=np.float32))


def test_video_drop_oldest_keeps_newest() -> None:
    queues = FrameQueues(video_capacity=2, audio_capacity=2)

    queues.put_video(_video(1))
    queues.put_video(_video(2))
    queues.put_video(_video(3))

    assert queues.drop_counts() == (1, 0)
    queues.begin_drain()
    first = queues.take_next(holdback_ns=0, expect_audio=True)
    second = queues.take_next(holdback_ns=0, expect_audio=True)
    assert first is not None and first.timestamp_ns == 2
    assert second is not None and second.timestamp_ns == 3
    assert queues.take_next(holdback_ns=0, expect_audio=True) is None


def test_audio_drop_oldest_keeps_newest() -> None:
    queues = FrameQueues(video_capacity=2, audio_capacity=2)

    queues.put_audio(_audio(1))
    queues.put_audio(_audio(2))
    queues.put_audio(_audio(3))

    assert queues.drop_counts() == (0, 1)
    queues.begin_drain()
    first = queues.take_next(holdback_ns=0, expect_audio=True)
    assert first is not None and first.timestamp_ns == 2


def test_holdback_gates_until_newest_moves() -> None:
    queues = FrameQueues(video_capacity=8, audio_capacity=8)
    queues.put_video(_video(0))
    queues.put_video(_video(100))

    assert queues.take_next(holdback_ns=150, expect_audio=True) is None

    queues.put_video(_video(200))
    first = queues.take_next(holdback_ns=150, expect_audio=True)
    assert first is not None and first.timestamp_ns == 0


def test_video_only_has_no_holdback() -> None:
    queues = FrameQueues(video_capacity=4, audio_capacity=4)
    queues.put_video(_video(0))

    first = queues.take_next(holdback_ns=1_000_000_000, expect_audio=False)

    assert first is not None and first.timestamp_ns == 0


def test_merge_picks_oldest_across_streams() -> None:
    queues = FrameQueues(video_capacity=8, audio_capacity=8)
    queues.put_video(_video(20))
    queues.put_audio(_audio(10))
    queues.begin_drain()

    first = queues.take_next(holdback_ns=0, expect_audio=True)
    second = queues.take_next(holdback_ns=0, expect_audio=True)
    assert first is not None and first.timestamp_ns == 10
    assert second is not None and second.timestamp_ns == 20


def test_begin_drain_releases_holdback() -> None:
    queues = FrameQueues(video_capacity=4, audio_capacity=4)
    queues.put_video(_video(0))
    assert queues.take_next(holdback_ns=1_000, expect_audio=True) is None

    queues.begin_drain()

    assert queues.draining
    item = queues.take_next(holdback_ns=1_000, expect_audio=True)
    assert item is not None and item.timestamp_ns == 0


def test_capacities_must_be_positive() -> None:
    try:
        FrameQueues(video_capacity=0, audio_capacity=4)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
