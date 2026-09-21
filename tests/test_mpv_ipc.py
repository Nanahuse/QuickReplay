"""mpv JSON IPC: endpoint generation, framing and request correlation."""

import json
import os
from decimal import Decimal

import pytest
from fake_mpv import FakeProcess, FakeTransport

from quickreplay.replay.errors import (
    MpvCommandError,
    MpvCommandTimeoutError,
    MpvIpcError,
    MpvProcessExitedError,
)
from quickreplay.replay.mpv_ipc import MpvIpcClient, make_ipc_endpoint, seconds_to_ns


def _client(transport: FakeTransport, process: FakeProcess) -> MpvIpcClient:
    return MpvIpcClient(transport, process=process, command_timeout_seconds=0.2)


def test_seconds_to_ns_is_exact() -> None:
    assert seconds_to_ns(Decimal("1.983")) == 1_983_000_000
    assert seconds_to_ns(Decimal("1.468135")) == 1_468_135_000
    assert seconds_to_ns(0) == 0
    assert seconds_to_ns(1) == 1_000_000_000
    assert seconds_to_ns(2.5) == 2_500_000_000
    assert seconds_to_ns("0.05") == 50_000_000


@pytest.mark.parametrize("value", [None, True, False, object()])
def test_seconds_to_ns_rejects_invalid(value: object) -> None:
    with pytest.raises(MpvIpcError):
        seconds_to_ns(value)


def test_endpoint_is_unique() -> None:
    first, _ = make_ipc_endpoint()
    second, _ = make_ipc_endpoint()
    assert first != second
    if os.name == "nt":
        assert first.startswith(r"\\.\pipe\quickreplay-mpv-")
    else:
        assert first.endswith(".sock")


def test_command_is_newline_terminated_json_with_integer_request_id() -> None:
    process = FakeProcess()
    transport = FakeTransport(process=process)
    client = _client(transport, process)

    client.command("get_property", "time-pos")

    raw = transport.raw[0]
    assert raw.endswith(b"\n")
    message = json.loads(raw.decode("utf-8"))
    assert message["command"] == ["get_property", "time-pos"]
    assert isinstance(message["request_id"], int)
    assert client.command("frame-step") is None


def test_interleaved_event_before_response() -> None:
    process = FakeProcess()

    def handler(command: list, request_id: int) -> dict:
        transport.inject_json({"event": "property-change", "name": "time-pos"})
        return {"error": "success", "data": 1.5}

    transport = FakeTransport(process=process, handler=handler)
    client = _client(transport, process)

    assert client.get_property("time-pos") == Decimal("1.5")


def test_wrong_request_id_is_not_mistaken_for_the_response() -> None:
    process = FakeProcess()
    sent_stale = {"done": False}

    def handler(command: list, request_id: int) -> dict:
        if not sent_stale["done"]:
            sent_stale["done"] = True
            transport.inject_json({"request_id": request_id + 1000, "error": "failure"})
        return {"error": "success", "data": 7}

    transport = FakeTransport(process=process, handler=handler)
    client = _client(transport, process)

    assert client.get_property("duration") == 7


def test_command_error_is_raised() -> None:
    process = FakeProcess()
    transport = FakeTransport(
        process=process, handler=lambda _c, _r: {"error": "property unavailable"}
    )
    client = _client(transport, process)

    with pytest.raises(MpvCommandError) as info:
        client.get_property("time-pos")
    assert info.value.error == "property unavailable"


def test_command_timeout() -> None:
    process = FakeProcess()
    transport = FakeTransport(process=process, handler=lambda _c, _r: None)
    client = _client(transport, process)

    with pytest.raises(MpvCommandTimeoutError):
        client.get_property("time-pos")


def test_process_exit_during_command() -> None:
    process = FakeProcess()

    def handler(command: list, request_id: int) -> None:
        process.mark_exited(1)
        return None

    transport = FakeTransport(process=process, handler=handler)
    client = _client(transport, process)

    with pytest.raises(MpvProcessExitedError):
        client.get_property("time-pos")


def test_command_before_send_after_process_exit() -> None:
    process = FakeProcess(running=False)
    transport = FakeTransport(process=process)
    client = _client(transport, process)

    with pytest.raises(MpvProcessExitedError):
        client.get_property("time-pos")
