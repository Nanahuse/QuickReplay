"""Time-bounded ring storage for finalized segments.

:class:`RingStorage` owns the lifetime of finalized
:class:`~quickreplay.recording.models.Segment` files produced by the segment
recorder.  It keeps segments in chronological order, deletes segments that fall
outside the configured buffer duration, and hands out snapshot leases that pin
segment files so a replay asset can be built without the files disappearing.

Retention is **timeline based**: the cutoff is derived from the newest
segment's ``session_end_ns`` and the configured buffer duration.  Whole
segments are kept or deleted; a segment is never partially trimmed.

The storage is intended for a single-threaded owner (the future encoder side of
the worker) and uses no internal locks.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from quickreplay.recording.errors import (
    RingStorageError,
    SegmentDeleteError,
    SegmentOrderError,
)
from quickreplay.recording.models import Segment

DeleteFile = Callable[[Path], None]


def _default_delete_file(path: Path) -> None:
    path.unlink()


@dataclass(slots=True)
class _RingEntry:
    """Internal ring entry.  Never exposed to callers."""

    segment: Segment
    pin_count: int = 0
    expired: bool = False
    last_delete_error: OSError | None = None


class RingStorage:
    """Chronological, time-bounded storage of finalized segments."""

    def __init__(
        self,
        *,
        buffer_duration_ns: int,
        delete_file: DeleteFile | None = None,
    ) -> None:
        if buffer_duration_ns <= 0:
            raise ValueError(f"buffer_duration_ns must be positive, got {buffer_duration_ns}")
        self._buffer_duration_ns = buffer_duration_ns
        self._delete_file: DeleteFile = delete_file or _default_delete_file
        self._entries: deque[_RingEntry] = deque()

    # -- queries -----------------------------------------------------------
    @property
    def buffer_duration_ns(self) -> int:
        """Configured retention window."""
        return self._buffer_duration_ns

    @property
    def segments(self) -> tuple[Segment, ...]:
        """Active (non-expired) segments, oldest first."""
        return tuple(entry.segment for entry in self._entries if not entry.expired)

    @property
    def segment_count(self) -> int:
        """Number of active segments."""
        return sum(1 for entry in self._entries if not entry.expired)

    @property
    def duration_ns(self) -> int:
        """Timeline span of the active segments (0 when empty)."""
        active = [entry.segment for entry in self._entries if not entry.expired]
        if not active:
            return 0
        return active[-1].session_end_ns - active[0].session_start_ns

    # -- mutation ----------------------------------------------------------
    def add(self, segment: Segment) -> None:
        """Register a finalized segment and apply retention.

        The new segment is always registered.  If retention cannot delete an
        expired file, a :class:`SegmentDeleteError` is raised after the segment
        has been registered, and the failed entry is kept so that a later
        operation can retry.
        """
        self._validate(segment)
        if not segment.path.exists():
            raise RingStorageError(f"segment file does not exist: {segment.path}")
        self._entries.append(_RingEntry(segment=segment))
        self._apply_retention()
        failed = self._retry_pending_deletions()
        if failed:
            raise SegmentDeleteError(tuple(failed))

    def snapshot(self) -> RingSnapshotLease:
        """Freeze the currently active segments and pin them.

        Expired segments are never included.  An empty snapshot is allowed.
        """
        entries = tuple(entry for entry in self._entries if not entry.expired)
        for entry in entries:
            entry.pin_count += 1
        return RingSnapshotLease(self, entries)

    def clear(self) -> None:
        """Expire and delete every segment, respecting active leases.

        Pinned segments are not deleted until their lease is released.  If any
        deletion fails, a :class:`SegmentDeleteError` is raised and the
        affected entry is kept for a later retry.
        """
        for entry in self._entries:
            entry.expired = True
        failed = self._retry_pending_deletions()
        if failed:
            raise SegmentDeleteError(tuple(failed))

    # -- internals ---------------------------------------------------------
    def _validate(self, segment: Segment) -> None:
        if not self._entries:
            return
        previous = self._entries[-1].segment
        if segment.id <= previous.id:
            raise SegmentOrderError(
                f"segment id {segment.id} is not greater than the previous id {previous.id}"
            )
        if segment.session_start_ns != previous.session_end_ns:
            raise SegmentOrderError(
                f"segment {segment.id} start {segment.session_start_ns} does not continue "
                f"the previous end {previous.session_end_ns}"
            )

    def _apply_retention(self) -> None:
        if not self._entries:
            return
        newest_end_ns = self._entries[-1].segment.session_end_ns
        cutoff_ns = newest_end_ns - self._buffer_duration_ns
        for entry in self._entries:
            if entry.segment.session_end_ns <= cutoff_ns:
                entry.expired = True

    def _retry_pending_deletions(self) -> list[Path]:
        failed: list[Path] = []
        survivors: deque[_RingEntry] = deque()
        for entry in self._entries:
            if entry.expired and entry.pin_count == 0:
                if self._delete_entry(entry):
                    continue
                failed.append(entry.segment.path)
            survivors.append(entry)
        self._entries = survivors
        return failed

    def _delete_entry(self, entry: _RingEntry) -> bool:
        try:
            self._delete_file(entry.segment.path)
        except FileNotFoundError:
            # Already gone: treat as a successful cleanup.
            entry.last_delete_error = None
            return True
        except OSError as exc:
            entry.last_delete_error = exc
            return False
        entry.last_delete_error = None
        return True

    def _release_entries(self, entries: tuple[_RingEntry, ...]) -> None:
        for entry in entries:
            if entry.pin_count > 0:
                entry.pin_count -= 1
        failed = self._retry_pending_deletions()
        if failed:
            raise SegmentDeleteError(tuple(failed))


class RingSnapshotLease:
    """A lease that pins a fixed set of segments while replay is prepared.

    ``segments`` stays readable after :meth:`release`, but the underlying files
    may already be deleted, so post-release file access is not guaranteed.
    """

    def __init__(self, storage: RingStorage, entries: tuple[_RingEntry, ...]) -> None:
        self._storage = storage
        self._entries = entries
        self._released = False

    @property
    def segments(self) -> tuple[Segment, ...]:
        """The pinned segments (immutable)."""
        return tuple(entry.segment for entry in self._entries)

    @property
    def released(self) -> bool:
        """Whether the lease has been released."""
        return self._released

    def release(self) -> None:
        """Release the pins.  Idempotent; deletion failures are raised."""
        if self._released:
            return
        self._released = True
        self._storage._release_entries(self._entries)

    def __enter__(self) -> RingSnapshotLease:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool:
        try:
            self.release()
        except SegmentDeleteError:
            # Do not mask an exception already propagating out of the with-block.
            if exc_type is None:
                raise
        return False
