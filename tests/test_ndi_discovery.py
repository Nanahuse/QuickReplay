"""NDI source discovery and runtime availability."""

from fake_ndi import FakeBackend

from quickreplay.input.models import NdiInputDescriptor
from quickreplay.input.ndi.discovery import discover_ndi_sources


def test_discovery_returns_descriptors_and_cleans_up() -> None:
    backend = FakeBackend(sources=("HOST (Cam A)", "HOST (Cam B)"))

    descriptors = discover_ndi_sources(backend=backend, timeout_ms=0)

    assert descriptors == (
        NdiInputDescriptor(source_name="HOST (Cam A)"),
        NdiInputDescriptor(source_name="HOST (Cam B)"),
    )
    assert backend.initialize_calls == 1
    assert backend.shutdown_calls == 1


def test_discovery_returns_empty_tuple() -> None:
    backend = FakeBackend(sources=())

    assert discover_ndi_sources(backend=backend, timeout_ms=0) == ()
    assert backend.shutdown_calls == 1
