"""Replay playback controller backed by an external mpv process.

The controller owns the mpv process lifecycle and the JSON IPC channel.  The
playback position always comes from mpv's ``time-pos`` property; the controller
keeps no frame counter and no playback clock of its own.  It does not touch the
recorder worker, the ring buffer or the replay asset lifecycle.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from quickreplay.replay.errors import (
    MpvExecutableNotFoundError,
    MpvIpcError,
    MpvProcessExitedError,
    MpvPropertyUnavailableError,
    MpvStartupError,
    ReplayControllerError,
)
from quickreplay.replay.models import ReplayAsset, SetPoint, frame_difference
from quickreplay.replay.mpv_ipc import (
    MpvIpcClient,
    MpvIpcTransport,
    default_transport_factory,
    make_ipc_endpoint,
    seconds_to_ns,
)
from quickreplay.replay.mpv_process import (
    MpvProcess,
    ProcessFactory,
    mpv_launch_arguments,
    spawn_mpv_process,
)

_NANOSECONDS = Decimal(1_000_000_000)


@dataclass(frozen=True, slots=True)
class ReplayControllerSettings:
    """Runtime settings for the replay controller (not persisted)."""

    mpv_executable: Path | str = "mpv"
    startup_timeout_seconds: float = 5.0
    command_timeout_seconds: float = 2.0
    shutdown_timeout_seconds: float = 2.0
    connect_retry_interval_seconds: float = 0.05


def frame_offset_seconds(frames: int, fps: Fraction) -> Fraction:
    """Exact playback offset for *frames* at *fps* (never a float)."""
    return Fraction(frames, 1) / fps


def fraction_to_seconds_text(value: Fraction) -> str:
    """Render an exact fraction as a decimal string for the IPC boundary."""
    return format(Decimal(value.numerator) / Decimal(value.denominator), "f")


class ReplayController:
    """Control one replay asset through an external mpv process."""

    def __init__(
        self,
        settings: ReplayControllerSettings,
        *,
        process_factory: ProcessFactory = spawn_mpv_process,
        transport_factory: Callable[[], MpvIpcTransport] = default_transport_factory,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._process_factory = process_factory
        self._transport_factory = transport_factory
        self._sleep = sleep

        self._asset: ReplayAsset | None = None
        self._process: MpvProcess | None = None
        self._ipc: MpvIpcClient | None = None
        self._endpoint: str | None = None
        self._cleanup_path: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def open(self, asset: ReplayAsset) -> None:
        """Start mpv for *asset* and leave the replay paused at the start."""
        if self._asset is not None:
            raise ReplayControllerError("a replay is already open")
        self._validate_asset(asset)
        endpoint, cleanup_path = make_ipc_endpoint()
        self._endpoint = endpoint
        self._cleanup_path = cleanup_path
        try:
            arguments = mpv_launch_arguments(self._settings.mpv_executable, endpoint, asset.path)
            self._process = self._spawn_process(arguments)
            transport = self._connect_with_retry(endpoint)
            self._ipc = MpvIpcClient(
                transport,
                process=self._process,
                command_timeout_seconds=self._settings.command_timeout_seconds,
            )
            self._wait_until_loaded()
            self._ipc.set_property("pause", True)
            self._asset = asset
        except BaseException:
            self._cleanup()
            raise

    def close(self) -> None:
        """Quit mpv and release every resource.  Safe to call repeatedly."""
        if self._asset is None and self._process is None:
            return
        try:
            if self._ipc is not None:
                try:
                    self._ipc.command("quit", wait=False)
                except Exception:  # noqa: BLE001 - best effort quit
                    pass
            self._shutdown_process()
        finally:
            self._cleanup()

    @property
    def asset(self) -> ReplayAsset | None:
        return self._asset

    @property
    def is_open(self) -> bool:
        return self._asset is not None

    # -- playback control --------------------------------------------------
    def play(self) -> None:
        self._require_open().set_property("pause", False)

    def pause(self) -> None:
        self._require_open().set_property("pause", True)

    def is_paused(self) -> bool:
        data = self._require_open().get_property("pause")
        if data is None:
            raise MpvPropertyUnavailableError("mpv pause is not available")
        return bool(data)

    def step_forward(self) -> None:
        self._require_open().command("frame-step")

    def step_backward(self) -> None:
        self._require_open().command("frame-back-step")

    def seek_frames(self, frames: int) -> None:
        """Move *frames* forward (positive) or backward (negative)."""
        if frames == 0:
            return
        if frames == 1:
            self.step_forward()
            return
        if frames == -1:
            self.step_backward()
            return
        asset = self._asset_or_raise()
        offset = frame_offset_seconds(frames, asset.fps)
        self._require_open().command("seek", fraction_to_seconds_text(offset), "relative+exact")

    def seek_absolute_ns(self, position_ns: int) -> None:
        """Seek to an absolute position, clamped to the asset timeline."""
        asset = self._asset_or_raise()
        clamped = min(max(position_ns, 0), asset.duration_ns)
        seconds = format(Decimal(clamped) / _NANOSECONDS, "f")
        self._require_open().command("seek", seconds, "absolute+exact")

    # -- position ----------------------------------------------------------
    def position_ns(self) -> int:
        data = self._require_open().get_property("time-pos")
        if data is None:
            raise MpvPropertyUnavailableError("mpv time-pos is not available")
        return seconds_to_ns(data)

    def set_point(self) -> SetPoint:
        return SetPoint(position_ns=self.position_ns())

    def time_difference_ns(self, point: SetPoint) -> int:
        return self.position_ns() - point.position_ns

    def frame_difference(self, point: SetPoint) -> int:
        asset = self._asset_or_raise()
        return frame_difference(
            current_position_ns=self.position_ns(),
            origin_position_ns=point.position_ns,
            fps=asset.fps,
        )

    # -- internals ---------------------------------------------------------
    def _validate_asset(self, asset: ReplayAsset) -> None:
        if not asset.path.exists():
            raise ReplayControllerError(f"the replay asset does not exist: {asset.path}")
        if asset.fps <= 0:
            raise ReplayControllerError(f"the replay asset has an invalid fps: {asset.fps}")
        if asset.duration_ns < 0:
            raise ReplayControllerError(
                f"the replay asset has a negative duration: {asset.duration_ns}"
            )

    def _spawn_process(self, arguments: list[str]) -> MpvProcess:
        try:
            return self._process_factory(arguments)
        except FileNotFoundError as exc:
            raise MpvExecutableNotFoundError(
                f"the mpv executable was not found: {arguments[0]!r}"
            ) from exc

    def _connect_with_retry(self, endpoint: str) -> MpvIpcTransport:
        process = self._process
        deadline = time.monotonic() + self._settings.startup_timeout_seconds
        last_error: Exception | None = None
        while True:
            if process is not None and process.poll() is not None:
                raise MpvStartupError("mpv exited before the IPC endpoint became available")
            transport = self._transport_factory()
            try:
                transport.connect(endpoint)
                return transport
            except (OSError, MpvIpcError) as exc:
                last_error = exc
                transport.close()
            if time.monotonic() >= deadline:
                raise MpvStartupError(
                    f"timed out waiting for the mpv IPC endpoint: {last_error}"
                ) from last_error
            self._sleep(self._settings.connect_retry_interval_seconds)

    def _wait_until_loaded(self) -> None:
        ipc = self._ipc
        process = self._process
        if ipc is None:  # pragma: no cover - defensive
            raise MpvStartupError("the mpv IPC channel is not connected")
        deadline = time.monotonic() + self._settings.startup_timeout_seconds
        while True:
            if ipc.get_property("duration") is not None:
                return
            if process is not None and process.poll() is not None:
                raise MpvStartupError("mpv exited before the replay file was loaded")
            if time.monotonic() >= deadline:
                raise MpvStartupError("timed out waiting for the replay file to load")
            self._sleep(self._settings.connect_retry_interval_seconds)

    def _shutdown_process(self) -> None:
        process = self._process
        if process is None:
            return
        timeout = self._settings.shutdown_timeout_seconds
        if process.poll() is not None:
            return
        if process.wait(timeout=timeout) is not None:
            return
        process.terminate()
        if process.wait(timeout=timeout) is not None:
            return
        process.kill()
        process.wait(timeout=timeout)

    def _cleanup(self) -> None:
        if self._ipc is not None:
            try:
                self._ipc.close()
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._ipc = None
        process = self._process
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=self._settings.shutdown_timeout_seconds)
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._process = None
        self._remove_endpoint()
        self._asset = None

    def _remove_endpoint(self) -> None:
        path = self._cleanup_path
        self._cleanup_path = None
        self._endpoint = None
        if path is not None:
            try:
                Path(path).unlink()
            except OSError:
                pass

    def _require_open(self) -> MpvIpcClient:
        if self._asset is None or self._ipc is None:
            raise ReplayControllerError("no replay is open")
        process = self._process
        if process is not None and process.poll() is not None:
            raise MpvProcessExitedError("the mpv process has exited")
        return self._ipc

    def _asset_or_raise(self) -> ReplayAsset:
        if self._asset is None:
            raise ReplayControllerError("no replay is open")
        return self._asset
