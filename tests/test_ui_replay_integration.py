"""Headless Set Point / frame-step integration with the real ReplayController.

The mpv process and IPC are faked (Phase 8 harness); the ReplayController
domain logic and frame-difference math are the real implementation.
"""

from fractions import Fraction
from pathlib import Path

from fake_mpv import FakeMpv

from quickreplay.replay.models import ReplayAsset


def _asset(tmp_path: Path, fps: Fraction) -> ReplayAsset:
    path = tmp_path / "replay.mkv"
    path.write_bytes(b"replay")
    return ReplayAsset(path, 12_000_000_000, fps)


def test_one_frame_difference_at_60fps(tmp_path: Path) -> None:
    fps = Fraction(60, 1)
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path, fps))
    try:
        mpv.state.time_pos = 2.0
        point = controller.set_point()
        mpv.state.frame_step_seconds = float(Fraction(1, 1) / fps)

        controller.step_forward()
        assert controller.frame_difference(point) == 1

        controller.step_forward()
        assert controller.frame_difference(point) == 2

        controller.step_backward()
        assert controller.frame_difference(point) == 1
    finally:
        controller.close()


def test_one_frame_difference_at_5994fps(tmp_path: Path) -> None:
    fps = Fraction(60000, 1001)
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path, fps))
    try:
        mpv.state.time_pos = 2.0
        point = controller.set_point()
        mpv.state.frame_step_seconds = float(Fraction(1, 1) / fps)

        controller.step_forward()
        assert controller.frame_difference(point) == 1

        controller.step_backward()
        assert controller.frame_difference(point) == 0
    finally:
        controller.close()
