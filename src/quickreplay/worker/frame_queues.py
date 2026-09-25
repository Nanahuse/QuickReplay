"""Bounded per-stream frame queues with drop-oldest and A/V ordering.

Video and audio are held in separate deques.  When a queue is full the oldest
frame is dropped so the capture side never blocks; drops are counted, not
silent.  The encode side pulls the oldest frame across both streams, holding
frames back until a configurable window has elapsed so a late stream can catch
up.
"""

import threading
from collections import deque

from quickreplay.input.models import AudioFrame, CaptureItem, VideoFrame


class FrameQueues:
    """Thread-safe bounded video/audio queues with drop-oldest behaviour."""

    def __init__(self, *, video_capacity: int, audio_capacity: int) -> None:
        if video_capacity <= 0 or audio_capacity <= 0:
            raise ValueError("queue capacities must be positive")
        self._lock = threading.Lock()
        self._ready = threading.Condition(self._lock)
        self._video: deque[VideoFrame] = deque()
        self._audio: deque[AudioFrame] = deque()
        self._video_capacity = video_capacity
        self._audio_capacity = audio_capacity
        self._draining = False
        self._video_drops = 0
        self._audio_drops = 0
        self._latest_video_ts: int | None = None
        self._latest_audio_ts: int | None = None

    # -- producer side -----------------------------------------------------
    def put_video(self, frame: VideoFrame) -> None:
        with self._ready:
            if len(self._video) >= self._video_capacity:
                self._video.popleft()
                self._video_drops += 1
            self._video.append(frame)
            self._latest_video_ts = _newer(self._latest_video_ts, frame.timestamp_ns)
            self._ready.notify_all()

    def put_audio(self, frame: AudioFrame) -> None:
        with self._ready:
            if len(self._audio) >= self._audio_capacity:
                self._audio.popleft()
                self._audio_drops += 1
            self._audio.append(frame)
            self._latest_audio_ts = _newer(self._latest_audio_ts, frame.timestamp_ns)
            self._ready.notify_all()

    def begin_drain(self) -> None:
        """Release the hold-back so the encode side processes everything."""
        with self._ready:
            self._draining = True
            self._ready.notify_all()

    # -- consumer side -----------------------------------------------------
    @property
    def draining(self) -> bool:
        with self._lock:
            return self._draining

    def empty(self) -> bool:
        with self._lock:
            return not self._video and not self._audio

    def drop_counts(self) -> tuple[int, int]:
        with self._lock:
            return self._video_drops, self._audio_drops

    def wait(self, timeout: float) -> None:
        with self._ready:
            if not self._video and not self._audio and not self._draining:
                self._ready.wait(timeout)

    def take_next(self, *, holdback_ns: int, expect_audio: bool) -> CaptureItem | None:
        """Return the oldest ready frame, or ``None`` if none may be emitted yet.

        ``expect_audio`` disables the hold-back for video-only sources so a
        Video-only input never pays an A/V latency. When draining, everything is emitted
        immediately.
        """
        with self._ready:
            if not self._video and not self._audio:
                return None
            take_video = self._pick_video()
            if not self._draining and expect_audio:
                oldest_ts = (
                    self._video[0].timestamp_ns if take_video else self._audio[0].timestamp_ns
                )
                newest = _newer_newest(self._latest_video_ts, self._latest_audio_ts)
                if newest is not None and oldest_ts > newest - holdback_ns:
                    return None
            if take_video:
                return self._video.popleft()
            return self._audio.popleft()

    def _pick_video(self) -> bool:
        if self._video and self._audio:
            return self._video[0].timestamp_ns <= self._audio[0].timestamp_ns
        return bool(self._video)


def _newer(current: int | None, candidate: int) -> int:
    if current is None or candidate > current:
        return candidate
    return current


def _newer_newest(first: int | None, second: int | None) -> int | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)
