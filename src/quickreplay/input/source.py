"""Common input source abstraction shared by the input implementations.

Both the NDI input (this phase) and the future Camera input implement this
protocol so they can be connected to the same recording pipeline.

``open`` prepares the source but does not necessarily establish the stream
format: NDI cannot report resolution or frame rate before the first frame
arrives.  ``stream_info`` therefore becomes available only after enough frames
have been read.  Every item returned by ``read`` must own its data; native
buffers are copied before being exposed and never handed out directly.
"""

from typing import Protocol

from quickreplay.input.models import CaptureItem, StreamInfo


class InputSource(Protocol):
    """A capture source that produces domain frames."""

    def open(self) -> None:
        """Acquire the source.  Must be idempotent-safe via ``close``."""
        ...

    @property
    def stream_info(self) -> StreamInfo | None:
        """The established stream format, or ``None`` before the first frame."""
        ...

    def read(self) -> CaptureItem | None:
        """Return the next frame, or ``None`` when nothing is available yet."""
        ...

    def close(self) -> None:
        """Release every native resource.  Safe to call multiple times."""
        ...
