"""Discover NDI sources without leaking native objects.

The finder is created, waited on, copied into plain
:class:`~quickreplay.input.models.NdiInputDescriptor` values and destroyed
before returning.  No native source object escapes this module.
"""

from quickreplay.input.models import NdiInputDescriptor
from quickreplay.input.ndi.backend import NdiBackend, PyNdiBackend

DEFAULT_DISCOVERY_TIMEOUT_MS = 2000
"""How long discovery waits for sources to appear."""


def discover_ndi_sources(
    *,
    timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS,
    backend: NdiBackend | None = None,
) -> tuple[NdiInputDescriptor, ...]:
    """Return the NDI sources currently advertised on the network."""
    active = backend or PyNdiBackend()
    active.initialize()
    try:
        names = active.discover(timeout_ms=timeout_ms)
    finally:
        active.shutdown()
    return tuple(NdiInputDescriptor(source_name=name) for name in names)
