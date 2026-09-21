"""Worker input factory: config -> source mapping and audio capability."""

from quickreplay.input.camera.source import CameraInputSource
from quickreplay.input.models import CameraInputConfig, NdiInputConfig
from quickreplay.input.ndi.source import NdiInputSource
from quickreplay.worker.inputs import (
    create_input_source,
    input_supports_audio,
    open_input_source,
)


def test_open_input_source_contract_matches_config() -> None:
    ndi = open_input_source(NdiInputConfig("PC (OBS)"))
    camera = open_input_source(CameraInputConfig("cam", 0, "any"))

    assert isinstance(create_input_source(NdiInputConfig("PC (OBS)")), NdiInputSource)
    assert isinstance(create_input_source(CameraInputConfig("cam", 0, "any")), CameraInputSource)
    assert isinstance(ndi.source, NdiInputSource)
    assert ndi.supports_audio is True
    assert isinstance(camera.source, CameraInputSource)
    assert camera.supports_audio is False
    assert input_supports_audio(NdiInputConfig("PC (OBS)")) is True
    assert input_supports_audio(CameraInputConfig("cam", 0, "any")) is False
