"""Manual local verification of ReplayController against a real mpv process.

This is not part of the automated test suite.  It builds a replay asset with
the existing recording/remux pipeline and drives it through mpv, printing the
observed playback positions.

Usage::

    uv run python tools/verify_replay_controller.py [path/to/mpv[.exe]]
"""

import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import numpy as np

from quickreplay.input.models import (
    AudioFrame,
    AudioStreamInfo,
    StreamInfo,
    VideoFrame,
    VideoStreamInfo,
)
from quickreplay.recording.models import RecordingSession
from quickreplay.recording.ring_storage import RingStorage
from quickreplay.recording.segment_recorder import SegmentRecorder
from quickreplay.replay.asset_builder import ReplayAssetBuilder
from quickreplay.replay.controller import ReplayController, ReplayControllerSettings
from quickreplay.replay.errors import MpvProcessExitedError
from quickreplay.replay.models import ReplayAsset, ReplaySnapshot
from quickreplay.units import NANOSECONDS_PER_SECOND, round_fraction

FPS = Fraction(60, 1)
WIDTH, HEIGHT = 320, 180
SAMPLE_RATE = 48000
CHANNELS = 2
DURATION_NS = 6_000_000_000


def build_replay(directory: Path) -> Path:
    info = StreamInfo(
        video=VideoStreamInfo(WIDTH, HEIGHT, FPS, "BGR24"),
        audio=AudioStreamInfo(SAMPLE_RATE, CHANNELS),
    )
    recorder = SegmentRecorder()
    recorder.start(RecordingSession(uuid4(), info, 0, directory))
    segments = []

    events: list[tuple[int, int, VideoFrame | AudioFrame]] = []
    index = 0
    while True:
        offset = round_fraction(Fraction(index * NANOSECONDS_PER_SECOND, 1) / FPS)
        if offset > DURATION_NS:
            break
        data = np.full((HEIGHT, WIDTH, 3), index % 256, dtype=np.uint8)
        events.append((offset, 0, VideoFrame(offset, WIDTH, HEIGHT, FPS, "BGR24", data)))
        index += 1

    total_samples = int(Fraction(DURATION_NS) * SAMPLE_RATE / NANOSECONDS_PER_SECOND)
    position = 0
    while position < total_samples:
        count = min(1024, total_samples - position)
        timestamp = round_fraction(Fraction(position * NANOSECONDS_PER_SECOND, SAMPLE_RATE))
        audio = np.zeros((CHANNELS, count), dtype=np.float32)
        events.append((timestamp, 1, AudioFrame(timestamp, SAMPLE_RATE, CHANNELS, count, audio)))
        position += count

    events.sort(key=lambda event: (event[0], event[1]))
    for _timestamp, _kind, frame in events:
        if isinstance(frame, VideoFrame):
            segments.extend(recorder.push_video(frame))
        else:
            recorder.push_audio(frame)

    last = recorder.finish()
    if last is not None:
        segments.append(last)
    recorder.close()

    ring = RingStorage(buffer_duration_ns=60 * NANOSECONDS_PER_SECOND)
    for segment in segments:
        ring.add(segment)
    with ring.snapshot() as lease:
        snapshot = ReplaySnapshot(segments=lease.segments, stream_info=info)
        asset = ReplayAssetBuilder().build(snapshot, directory / "replay")
    ring.clear()
    return asset.path


def main() -> int:
    executable = sys.argv[1] if len(sys.argv) > 1 else "mpv"
    with tempfile.TemporaryDirectory(prefix="qr_controller_") as tmp:
        directory = Path(tmp)
        asset_path = build_replay(directory)
        print(f"replay asset: {asset_path}", flush=True)

        settings = ReplayControllerSettings(mpv_executable=executable)
        controller = ReplayController(settings)
        ok = True
        try:
            controller.open(ReplayAsset(asset_path, DURATION_NS, FPS))
            print(f"opened; paused={controller.is_paused()} position={controller.position_ns()}")

            controller.play()
            time.sleep(0.6)
            moving = controller.position_ns()
            controller.pause()
            time.sleep(0.3)
            stable = controller.position_ns()
            print(f"play -> {moving} ns; pause -> {stable} ns")
            ok = ok and moving > 0 and abs(stable - moving) < 40_000_000

            boundary_ns = 2_000_000_000
            controller.seek_absolute_ns(boundary_ns - 50_000_000)
            time.sleep(0.3)
            forward = []
            for _ in range(5):
                controller.step_forward()
                time.sleep(0.1)
                forward.append(controller.position_ns())
            print("forward steps:", [round(p / 1e6, 1) for p in forward])

            backward = []
            for _ in range(5):
                controller.step_backward()
                time.sleep(0.1)
                backward.append(controller.position_ns())
            print("backward steps:", [round(p / 1e6, 1) for p in backward])

            ok = ok and all(b > a for a, b in zip(forward, forward[1:], strict=False))
            ok = ok and all(b < a for a, b in zip(backward, backward[1:], strict=False))
            ok = ok and forward[0] < boundary_ns < forward[-1]
            ok = ok and backward[0] > boundary_ns > backward[-1]

            controller.seek_absolute_ns(1_000_000_000)
            time.sleep(0.3)
            before = controller.position_ns()
            controller.seek_frames(20)
            time.sleep(0.3)
            after = controller.position_ns()
            print(f"+20 frames: {before} -> {after} (delta {after - before} ns)")
            expected = int(Fraction(20, 1) / FPS * NANOSECONDS_PER_SECOND)
            ok = ok and abs((after - before) - expected) < 20_000_000

            controller.seek_absolute_ns(3_000_000_000)
            time.sleep(0.3)
            mid = controller.position_ns()
            print(f"absolute seek to 3.0s -> {mid} ns")
            ok = ok and abs(mid - 3_000_000_000) < 40_000_000

            point = controller.set_point()
            controller.seek_frames(10)
            time.sleep(0.2)
            print(
                f"set point: time diff {controller.time_difference_ns(point)} ns, "
                f"frame diff {controller.frame_difference(point)}"
            )

            # Simulate an external window close and confirm detection.
            ipc = getattr(controller, "_ipc", None)  # noqa: B009 - verification tool
            if ipc is not None:
                ipc.command("quit", wait=False)
            time.sleep(0.5)
            try:
                controller.play()
            except MpvProcessExitedError:
                print("unexpected exit detected: MpvProcessExitedError")
            else:
                print("unexpected exit NOT detected")
                ok = False
        finally:
            controller.close()

        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
