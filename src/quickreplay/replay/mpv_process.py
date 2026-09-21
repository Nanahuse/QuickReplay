"""External mpv process management.

mpv runs as a separate process; QuickReplay never embeds libmpv.  stdout and
stderr are discarded, so all control flows through the JSON IPC channel.
"""

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from quickreplay.replay.errors import MpvExecutableNotFoundError


class MpvProcess(Protocol):
    """The process operations the replay controller needs."""

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    @property
    def returncode(self) -> int | None: ...


ProcessFactory = Callable[[Sequence[str]], MpvProcess]


def mpv_launch_arguments(executable: Path | str, endpoint: str, asset_path: Path) -> list[str]:
    """Build the mpv command line used for replay playback."""
    return [
        str(executable),
        "--no-config",
        "--terminal=no",
        f"--input-ipc-server={endpoint}",
        "--pause=yes",
        "--keep-open=yes",
        "--force-window=yes",
        "--hr-seek=yes",
        "--hr-seek-framedrop=no",
        "--hwdec=no",
        str(asset_path),
    ]


class SubprocessMpvProcess:
    """Thin wrapper around :class:`subprocess.Popen`."""

    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int | None:
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    @property
    def returncode(self) -> int | None:
        return self._process.returncode


def spawn_mpv_process(arguments: Sequence[str]) -> MpvProcess:
    """Start mpv with *arguments*, mapping a missing executable to an error."""
    try:
        process = subprocess.Popen(  # noqa: S603 - explicit, validated arguments
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise MpvExecutableNotFoundError(
            f"the mpv executable was not found: {arguments[0]!r}"
        ) from exc
    except OSError as exc:
        raise MpvExecutableNotFoundError(f"could not start mpv: {exc}") from exc
    return SubprocessMpvProcess(process)
