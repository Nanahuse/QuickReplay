"""mpv JSON IPC: endpoint generation, transports and a request/response client.

Only the JSON IPC channel is used to control mpv; stdout/stderr are never
parsed.  A dedicated reader thread turns the blocking pipe/socket into timed
line reads so command responses can be awaited without ever blocking forever.
"""

import json
import os
import queue
import socket
import tempfile
import threading
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

from quickreplay.replay.errors import (
    MpvCommandError,
    MpvCommandTimeoutError,
    MpvIpcError,
    MpvProcessExitedError,
)

_NANOSECONDS = Decimal(1_000_000_000)


class _IpcEof:
    """Sentinel returned when the IPC reader reaches end-of-file."""


IPC_EOF = _IpcEof()


def seconds_to_ns(value: Any) -> int:
    """Convert an mpv seconds value to integer nanoseconds.

    mpv numbers arrive as :class:`~decimal.Decimal` (parsed without a binary
    float round trip); integers and numeric strings are accepted too.
    """
    if value is None or isinstance(value, bool):
        raise MpvIpcError(f"cannot convert {value!r} to nanoseconds")
    if isinstance(value, Decimal):
        seconds = value
    elif isinstance(value, int | str):
        seconds = Decimal(value)
    elif isinstance(value, float):
        seconds = Decimal(str(value))
    else:
        raise MpvIpcError(f"cannot convert {type(value).__name__} to nanoseconds")
    return int((seconds * _NANOSECONDS).to_integral_value(rounding=ROUND_HALF_UP))


def make_ipc_endpoint() -> tuple[str, str | None]:
    """Return a unique ``(endpoint, cleanup_path)`` for one mpv instance."""
    token = uuid.uuid4()
    if os.name == "nt":
        return rf"\\.\pipe\quickreplay-mpv-{token}", None
    path = os.path.join(tempfile.gettempdir(), f"quickreplay-mpv-{token}.sock")
    return path, path


class MpvIpcTransport(Protocol):
    """A line-oriented, byte transport to the mpv IPC endpoint."""

    def connect(self, endpoint: str) -> None: ...

    def write_line(self, data: bytes) -> None: ...

    def read_line(self, timeout: float) -> bytes | _IpcEof | None: ...

    def close(self) -> None: ...


class _LineReaderMixin:
    """Turns a blocking byte source into timed ``read_line`` calls.

    Reading happens on a daemon thread so ``read_line`` can honour a timeout
    without blocking the command dispatch.  Reading and writing use separate
    handles (or raw ``os.read``/``os.write``) so a blocked read can never hold
    a lock that a write needs.
    """

    _lines: queue.Queue[bytes | _IpcEof]
    _reader: threading.Thread | None

    def _start_reader(self) -> None:
        self._reader = threading.Thread(target=self._pump, name="qr-mpv-ipc", daemon=True)
        self._reader.start()

    def _read_chunk(self) -> bytes:
        raise NotImplementedError

    def _pump(self) -> None:
        buffer = b""
        try:
            while True:
                chunk = self._read_chunk()
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._lines.put(line + b"\n")
            if buffer:
                self._lines.put(buffer + b"\n")
        except Exception:  # noqa: BLE001 - stream closed during shutdown
            pass
        finally:
            self._lines.put(IPC_EOF)

    def read_line(self, timeout: float) -> bytes | _IpcEof | None:
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            return None


class WindowsPipeTransport(_LineReaderMixin):
    """mpv IPC over a Windows named pipe."""

    def __init__(self) -> None:
        self._file: Any = None
        self._fd: int | None = None
        self._lines: queue.Queue[bytes | _IpcEof] = queue.Queue()
        self._reader = None
        self._closed = False

    def connect(self, endpoint: str) -> None:
        try:
            self._file = open(endpoint, "r+b", buffering=0)  # noqa: SIM115 - kept open
        except OSError as exc:
            raise MpvIpcError(f"could not connect to the mpv IPC pipe: {exc}") from exc
        self._fd = self._file.fileno()
        self._start_reader()

    def _read_chunk(self) -> bytes:
        assert self._fd is not None
        # A blocking ReadFile on a synchronous pipe handle also blocks writes,
        # so poll for available bytes with PeekNamedPipe before reading.
        while not self._closed:
            if _pipe_bytes_available(self._fd) > 0:
                return os.read(self._fd, 65536)
            time.sleep(0.002)
        return b""

    def write_line(self, data: bytes) -> None:
        fd = self._fd
        if fd is None:
            raise MpvIpcError("the mpv IPC pipe is not connected")
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
        except OSError as exc:
            raise MpvIpcError(f"could not write to the mpv IPC pipe: {exc}") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass


class UnixSocketTransport(_LineReaderMixin):
    """mpv IPC over a Unix domain socket."""

    def __init__(self) -> None:
        self._socket: socket.socket | None = None
        self._stream: Any = None
        self._lines: queue.Queue[bytes | _IpcEof] = queue.Queue()
        self._reader = None
        self._closed = False

    def connect(self, endpoint: str) -> None:
        address_family = getattr(socket, "AF_UNIX", None)
        if address_family is None:  # pragma: no cover - platform guard
            raise MpvIpcError("Unix domain sockets are not available on this platform")
        sock = socket.socket(address_family, socket.SOCK_STREAM)
        try:
            sock.connect(endpoint)
        except OSError as exc:
            sock.close()
            raise MpvIpcError(f"could not connect to the mpv IPC socket: {exc}") from exc
        self._socket = sock
        self._stream = sock.makefile("rb")
        self._start_reader()

    def _read_chunk(self) -> bytes:
        return self._stream.readline()

    def write_line(self, data: bytes) -> None:
        if self._socket is None:
            raise MpvIpcError("the mpv IPC socket is not connected")
        try:
            self._socket.sendall(data)
        except OSError as exc:
            raise MpvIpcError(f"could not write to the mpv IPC socket: {exc}") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass


def _pipe_bytes_available(fd: int) -> int:
    """Bytes ready to read on a Windows pipe, without blocking the handle."""
    import ctypes  # noqa: PLC0415 - Windows-only helper

    msvcrt = __import__("msvcrt")
    windll = getattr(ctypes, "WinDLL")  # noqa: B009 - Windows-only attribute
    kernel32 = windll("kernel32", use_last_error=True)
    handle = getattr(msvcrt, "get_osfhandle")(fd)  # noqa: B009 - Windows-only
    available = ctypes.c_ulong(0)
    ok = kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None)
    if not ok:
        get_last_error = getattr(ctypes, "get_last_error")  # noqa: B009 - Windows-only
        raise OSError(get_last_error(), "PeekNamedPipe failed")
    return int(available.value)


def default_transport_factory() -> MpvIpcTransport:
    """Create the platform IPC transport."""
    if os.name == "nt":
        return WindowsPipeTransport()
    return UnixSocketTransport()


class MpvIpcClient:
    """Correlates JSON IPC requests with their responses by ``request_id``."""

    def __init__(
        self,
        transport: MpvIpcTransport,
        *,
        process: Any,
        command_timeout_seconds: float,
    ) -> None:
        self._transport = transport
        self._process = process
        self._command_timeout_seconds = command_timeout_seconds
        self._request_id = 0
        self._pending: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._transport.close()

    def command(self, *args: object, wait: bool = True) -> Any:
        """Send a command and (by default) return its ``data`` payload."""
        with self._lock:
            if wait:
                self._raise_if_exited()
            self._request_id += 1
            request_id = self._request_id
            payload = {"command": list(args), "request_id": request_id}
            self._transport.write_line(json.dumps(payload).encode("utf-8") + b"\n")
            if not wait:
                return None
            return self._await_response(request_id, list(args))

    def get_property(self, name: str) -> Any:
        return self.command("get_property", name)

    def set_property(self, name: str, value: object) -> None:
        self.command("set_property", name, value)

    def _await_response(self, request_id: int, command: list[object]) -> Any:
        deadline = time.monotonic() + self._command_timeout_seconds
        while True:
            pending = self._pending.pop(request_id, None)
            if pending is not None:
                return self._unwrap(pending, command)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MpvCommandTimeoutError(
                    f"mpv did not answer {command!r} within {self._command_timeout_seconds}s"
                )
            line = self._transport.read_line(remaining)
            if line is None:
                if self._process.poll() is not None:
                    raise MpvProcessExitedError("the mpv process exited during a command")
                continue
            if isinstance(line, _IpcEof):
                raise MpvProcessExitedError("the mpv IPC channel reached EOF")
            self._handle_line(line, request_id, command)

    def _handle_line(self, line: bytes, request_id: int, command: list[object]) -> None:
        try:
            message = json.loads(line, parse_float=Decimal)
        except ValueError as exc:
            raise MpvIpcError(f"invalid mpv IPC message: {exc}") from exc
        if not isinstance(message, dict) or "request_id" not in message:
            return  # an asynchronous event: ignore it
        response_id = message.get("request_id")
        if response_id == request_id:
            self._pending[request_id] = message
        elif isinstance(response_id, int):
            self._pending[response_id] = message

    def _unwrap(self, message: dict[str, Any], command: list[object]) -> Any:
        error = message.get("error", "success")
        if error != "success":
            raise MpvCommandError(str(error), command)
        return message.get("data")

    def _raise_if_exited(self) -> None:
        if self._process.poll() is not None:
            raise MpvProcessExitedError("the mpv process has exited")
