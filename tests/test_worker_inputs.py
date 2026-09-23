"""Worker input factory and discovery contracts."""

from quickreplay.input.models import NdiInputConfig
from quickreplay.input.ndi.source import NdiInputSource
from quickreplay.worker.inputs import create_input_source, input_supports_audio, open_input_source


def test_open_input_source_contract_matches_config() -> None:
    config = NdiInputConfig("PC (OBS)")
    source = open_input_source(config)

    assert isinstance(create_input_source(config), NdiInputSource)
    assert isinstance(source.source, NdiInputSource)
    assert source.supports_audio is True
    assert input_supports_audio(config) is True
