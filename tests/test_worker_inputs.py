"""Worker input factory: config -> source mapping and audio capability."""

from quickreplay.input.camera.source import CameraInputSource
from quickreplay.input.models import CameraInputConfig, NdiInputConfig
from quickreplay.input.ndi.source import NdiInputSource
from quickreplay.worker.inputs import (
    create_input_source,
    input_supports_audio,
    open_input_source,
)


def test_input_supports_audio() -> None:
    assert input_supports_audio(NdiInputConfig("PC (OBS)")) is True
    assert input_supports_audio(CameraInputConfig("cam", 0, "any")) is False


def test_create_input_source_builds_the_matching_source() -> None:
    assert isinstance(create_input_source(NdiInputConfig("PC (OBS)")), NdiInputSource)
    assert isinstance(create_input_source(CameraInputConfig("cam", 0, "any")), CameraInputSource)


def test_open_input_source_reports_audio_capability() -> None:
    ndi = open_input_source(NdiInputConfig("PC (OBS)"))
    camera = open_input_source(CameraInputConfig("cam", 0, "any"))
    assert isinstance(ndi.source, NdiInputSource)
    assert ndi.supports_audio is True
    assert isinstance(camera.source, CameraInputSource)
    assert camera.supports_audio is False
