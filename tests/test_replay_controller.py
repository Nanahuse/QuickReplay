"""ReplayController: lifecycle, playback control, position and shutdown."""

from fractions import Fraction
from pathlib import Path
from typing import NoReturn

import pytest
from fake_mpv import FakeMpv, FakeTransport

from quickreplay.replay.controller import (
    ReplayController,
    ReplayControllerSettings,
    frame_offset_seconds,
)
from quickreplay.replay.errors import (
    MpvExecutableNotFoundError,
    MpvProcessExitedError,
    MpvPropertyUnavailableError,
    MpvStartupError,
    ReplayControllerError,
)
from quickreplay.replay.models import ReplayAsset

FPS_60 = Fraction(60, 1)
FPS_5994 = Fraction(60000, 1001)


def _asset(
    tmp_path: Path,
    *,
    fps: Fraction = FPS_60,
    duration_ns: int = 2_000_000_000,
    name: str = "replay.mkv",
) -> ReplayAsset:
    path = tmp_path / name
    path.write_bytes(b"replay")
    return ReplayAsset(path=path, duration_ns=duration_ns, fps=fps)


def test_open_launches_mpv_with_expected_arguments(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    asset = _asset(tmp_path)

    controller.open(asset)
    try:
        arguments = mpv.arguments
        assert arguments is not None
        for flag in (
            "--no-config",
            "--terminal=no",
            "--osc=no",
            "--pause=yes",
            "--keep-open=yes",
            "--force-window=yes",
            "--hr-seek=yes",
            "--hr-seek-framedrop=no",
            "--hwdec=no",
        ):
            assert flag in arguments
        assert any(argument.startswith("--input-ipc-server=") for argument in arguments)
        assert arguments[-1] == str(asset.path)
    finally:
        controller.close()


def test_open_leaves_replay_paused(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        assert controller.is_open
        assert controller.asset is not None
        assert ["set_property", "pause", True] in mpv.transport.commands()
        assert controller.is_paused() is True
    finally:
        controller.close()


def test_double_open_is_rejected(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path, name="a.mkv"))
    try:
        with pytest.raises(ReplayControllerError):
            controller.open(_asset(tmp_path, name="b.mkv"))
    finally:
        controller.close()


def test_missing_asset_does_not_start_mpv(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    missing = ReplayAsset(tmp_path / "missing.mkv", 1_000_000_000, FPS_60)

    with pytest.raises(ReplayControllerError):
        controller.open(missing)

    assert mpv.arguments is None
    assert not controller.is_open


def test_missing_executable_is_mapped(tmp_path: Path) -> None:
    def factory(_arguments) -> NoReturn:
        raise FileNotFoundError("mpv")

    controller = ReplayController(
        ReplayControllerSettings(mpv_executable="does-not-exist"),
        process_factory=factory,
        transport_factory=FakeTransport,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(MpvExecutableNotFoundError):
        controller.open(_asset(tmp_path))


def test_play_and_pause_send_set_property(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        controller.play()
        controller.pause()
        commands = mpv.transport.commands()
        assert ["set_property", "pause", False] in commands
        assert ["set_property", "pause", True] in commands
    finally:
        controller.close()


def test_is_paused_queries_mpv_property(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        mpv.state.pause = False
        assert controller.is_paused() is False
        mpv.state.pause = True
        assert controller.is_paused() is True
        assert ["get_property", "pause"] in mpv.transport.commands()
    finally:
        controller.close()


def test_step_forward_and_backward(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        controller.step_forward()
        controller.step_backward()
        commands = mpv.transport.commands()
        assert ["frame-step"] in commands
        assert ["frame-back-step"] in commands
    finally:
        controller.close()


def test_seek_frames_single_step_delegates(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        controller.seek_frames(1)
        controller.seek_frames(-1)
        commands = mpv.transport.commands()
        assert ["frame-step"] in commands
        assert ["frame-back-step"] in commands
        assert not any(command and command[0] == "seek" for command in commands)
    finally:
        controller.close()


def test_seek_frames_zero_is_a_noop(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        before = len(mpv.transport.sent)
        controller.seek_frames(0)
        assert len(mpv.transport.sent) == before
    finally:
        controller.close()


def test_frame_offset_seconds_is_exact() -> None:
    assert frame_offset_seconds(20, FPS_60) == Fraction(1, 3)
    assert frame_offset_seconds(20, FPS_5994) == Fraction(20, 1) / Fraction(60000, 1001)
    assert frame_offset_seconds(-20, FPS_60) == Fraction(-1, 3)


def test_seek_frames_relative_exact(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        controller.seek_frames(20)
        seek = [command for command in mpv.transport.commands() if command[0] == "seek"][-1]
        assert seek[2] == "relative+exact"
        assert abs(float(seek[1]) - 1 / 3) < 1e-9
    finally:
        controller.close()


def test_seek_frames_negative_relative(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        controller.seek_frames(-20)
        seek = [command for command in mpv.transport.commands() if command[0] == "seek"][-1]
        assert seek[2] == "relative+exact"
        assert abs(float(seek[1]) + 1 / 3) < 1e-9
    finally:
        controller.close()


def test_seek_frames_5994_uses_exact_fraction(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path, fps=FPS_5994))
    try:
        controller.seek_frames(20)
        seek = [command for command in mpv.transport.commands() if command[0] == "seek"][-1]
        expected = float(Fraction(20, 1) / FPS_5994)
        assert abs(float(seek[1]) - expected) < 1e-9
    finally:
        controller.close()


def test_seek_absolute_is_clamped(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path, duration_ns=2_000_000_000))
    try:
        controller.seek_absolute_ns(-5)
        controller.seek_absolute_ns(5_000_000_000)
        controller.seek_absolute_ns(1_500_000_000)
        seeks = [command for command in mpv.transport.commands() if command[0] == "seek"]
        assert seeks[0] == ["seek", "0", "absolute+exact"]
        assert seeks[1] == ["seek", "2", "absolute+exact"]
        assert seeks[2] == ["seek", "1.5", "absolute+exact"]
    finally:
        controller.close()


def test_position_ns_conversion(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        mpv.state.time_pos = 1.983
        assert controller.position_ns() == 1_983_000_000
        mpv.state.time_pos = 1.468135
        assert controller.position_ns() == 1_468_135_000
    finally:
        controller.close()


def test_position_unavailable_is_explicit(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        mpv.state.time_pos = None
        with pytest.raises(MpvPropertyUnavailableError):
            controller.position_ns()
    finally:
        controller.close()


def test_set_point_and_time_difference(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        mpv.state.time_pos = 2.0
        point = controller.set_point()
        assert point.position_ns == 2_000_000_000
        mpv.state.time_pos = 2.05
        assert controller.time_difference_ns(point) == 50_000_000
    finally:
        controller.close()


def test_frame_difference_at_60fps(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        mpv.state.time_pos = 2.0
        point = controller.set_point()
        mpv.state.time_pos = 2.05
        assert controller.frame_difference(point) == 3
    finally:
        controller.close()


def test_frame_difference_at_5994fps(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path, fps=FPS_5994))
    try:
        mpv.state.time_pos = 2.0
        point = controller.set_point()
        mpv.state.time_pos = 2.05
        assert controller.frame_difference(point) == 3
    finally:
        controller.close()


def test_operation_after_unexpected_exit(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    controller.open(_asset(tmp_path))
    try:
        mpv.process.mark_exited(3)
        with pytest.raises(MpvProcessExitedError):
            controller.play()
    finally:
        controller.close()


def test_close_is_idempotent_and_keeps_the_asset(tmp_path: Path) -> None:
    mpv = FakeMpv()
    controller = mpv.controller()
    asset = _asset(tmp_path)
    controller.open(asset)

    controller.close()
    controller.close()

    assert mpv.transport.closed
    assert not controller.is_open
    assert asset.path.exists()


def test_graceful_shutdown_does_not_terminate(tmp_path: Path) -> None:
    mpv = FakeMpv(exit_on_quit=True)
    controller = mpv.controller()
    controller.open(_asset(tmp_path))

    controller.close()

    assert mpv.process.terminate_calls == 0
    assert mpv.process.kill_calls == 0


def test_forced_shutdown_terminates(tmp_path: Path) -> None:
    mpv = FakeMpv(exit_on_quit=False, wait_results=[None, 0])
    controller = mpv.controller()
    controller.open(_asset(tmp_path))

    controller.close()

    assert mpv.process.terminate_calls == 1
    assert mpv.process.kill_calls == 0


def test_forced_shutdown_falls_back_to_kill(tmp_path: Path) -> None:
    mpv = FakeMpv(exit_on_quit=False, wait_results=[None, None, 0], terminate_works=False)
    controller = mpv.controller()
    controller.open(_asset(tmp_path))

    controller.close()

    assert mpv.process.terminate_calls == 1
    assert mpv.process.kill_calls == 1


def test_startup_timeout_cleans_up(tmp_path: Path) -> None:
    mpv = FakeMpv(connect_error=OSError("pipe not ready"), startup_timeout_seconds=0.01)
    controller = mpv.controller(startup_timeout_seconds=0.01)

    with pytest.raises(MpvStartupError):
        controller.open(_asset(tmp_path))

    assert not controller.is_open
    assert mpv.process.terminate_calls >= 1


def test_process_exit_before_connect_fails_fast(tmp_path: Path) -> None:
    mpv = FakeMpv(running=False)
    controller = mpv.controller()

    with pytest.raises(MpvStartupError):
        controller.open(_asset(tmp_path))

    assert mpv.process.terminate_calls == 0
