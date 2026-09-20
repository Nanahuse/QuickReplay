"""NdiInputSource behaviour: lifecycle, capture, errors and format changes."""

from fractions import Fraction

import pytest
from fake_ndi import FakeBackend, fake_audio, fake_metadata, fake_video

from quickreplay.input.models import AudioFrame, NdiInputConfig, VideoFrame
from quickreplay.input.ndi.errors import (
    NdiCaptureError,
    NdiFormatChangeError,
    NdiReceiverError,
    NdiSourceNotFoundError,
)
from quickreplay.input.ndi.source import NdiInputSource


def _source(backend: FakeBackend, name: str = "My Source") -> NdiInputSource:
    return NdiInputSource(NdiInputConfig(source_name=name), backend=backend, discovery_timeout_ms=0)


def test_source_not_found_cleans_up() -> None:
    backend = FakeBackend(sources=())
    source = _source(backend)

    with pytest.raises(NdiSourceNotFoundError):
        source.open()

    assert backend.initialize_calls == 1
    assert backend.shutdown_calls == 1
    assert backend.create_receiver_calls == 0


def test_open_resolves_machine_prefixed_name() -> None:
    backend = FakeBackend(sources=("HOST (My Source)",))
    source = _source(backend)

    source.open()
    try:
        assert backend.receivers[0].source_name() == "HOST (My Source)"
    finally:
        source.close()


def test_read_returns_none_when_nothing_is_available() -> None:
    backend = FakeBackend(sources=("My Source",), script=[])
    source = _source(backend)
    source.open()
    try:
        assert source.read() is None
    finally:
        source.close()


def test_stream_info_is_lazy_and_includes_audio_once_seen() -> None:
    video = fake_video(width=8, height=4, fps=Fraction(60000, 1001), timestamp_ns=1_234_567_800)
    audio = fake_audio(timestamp_ns=1_234_567_800)
    backend = FakeBackend(sources=("My Source",), script=[video, audio])
    source = _source(backend)
    source.open()
    try:
        assert source.stream_info is None

        video_frame = source.read()
        assert isinstance(video_frame, VideoFrame)
        assert source.stream_info is not None
        assert source.stream_info.audio is None
        assert source.stream_info.video.width == 8
        assert source.stream_info.video.height == 4
        assert source.stream_info.video.fps == Fraction(60000, 1001)
        assert source.stream_info.video.pixel_format == "UYVY"

        audio_frame = source.read()
        assert isinstance(audio_frame, AudioFrame)
        assert source.stream_info.audio is not None
        assert source.stream_info.audio.sample_rate == 48000
        assert source.stream_info.audio.channels == 2
    finally:
        source.close()


def test_timestamp_is_taken_from_the_frame() -> None:
    backend = FakeBackend(sources=("My Source",), script=[fake_video(timestamp_ns=1_234_567_800)])
    source = _source(backend)
    source.open()
    try:
        frame = source.read()
        assert frame is not None
        assert frame.timestamp_ns == 1_234_567_800
    finally:
        source.close()


def test_metadata_is_discarded_and_freed() -> None:
    backend = FakeBackend(sources=("My Source",), script=[fake_metadata()])
    source = _source(backend)
    source.open()
    try:
        assert source.read() is None
        receiver = backend.receivers[0]
        assert receiver.metadata_frees == 1
        assert receiver.video_frees == 0
        assert receiver.audio_frees == 0
    finally:
        source.close()


def test_native_buffers_are_freed_after_conversion() -> None:
    video = fake_video()
    audio = fake_audio()
    backend = FakeBackend(sources=("My Source",), script=[video, audio])
    source = _source(backend)
    source.open()
    try:
        source.read()
        source.read()
        assert video.handle.freed
        assert audio.handle.freed
        assert backend.receivers[0].video_frees == 1
        assert backend.receivers[0].audio_frees == 1
    finally:
        source.close()


def test_video_format_change_is_rejected() -> None:
    backend = FakeBackend(
        sources=("My Source",),
        script=[fake_video(width=1920, height=1080), fake_video(width=1280, height=720)],
    )
    source = _source(backend)
    source.open()
    try:
        source.read()
        with pytest.raises(NdiFormatChangeError):
            source.read()
    finally:
        source.close()


def test_audio_format_change_is_rejected() -> None:
    backend = FakeBackend(
        sources=("My Source",),
        script=[fake_audio(channels=2), fake_audio(channels=1)],
    )
    source = _source(backend)
    source.open()
    try:
        source.read()
        with pytest.raises(NdiFormatChangeError):
            source.read()
    finally:
        source.close()


def test_capture_error_propagates() -> None:
    backend = FakeBackend(
        sources=("My Source",), script=[fake_video(), NdiCaptureError("disconnected")]
    )
    source = _source(backend)
    source.open()
    try:
        source.read()
        with pytest.raises(NdiCaptureError):
            source.read()
    finally:
        source.close()


def test_close_is_idempotent_and_destroys_receiver_once() -> None:
    backend = FakeBackend(sources=("My Source",))
    source = _source(backend)
    source.open()
    receiver = backend.receivers[0]

    source.close()
    source.close()

    assert receiver.destroyed
    assert backend.shutdown_calls == 1
    with pytest.raises(NdiReceiverError):
        source.read()


def test_open_failure_cleans_up_the_runtime_reference() -> None:
    backend = FakeBackend(
        sources=("My Source",), receiver_error=NdiReceiverError("could not create receiver")
    )
    source = _source(backend)

    with pytest.raises(NdiReceiverError):
        source.open()

    assert backend.initialize_calls == 1
    assert backend.shutdown_calls == 1

    source.close()  # safe after a failed open
    assert backend.shutdown_calls == 1
