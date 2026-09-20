"""Tests for RingStorage snapshot leases, pinning and clear."""

from collections.abc import Callable

import pytest

from quickreplay.recording.models import Segment
from quickreplay.recording.ring_storage import RingStorage

SECOND = 1_000_000_000


def _ring_with_two(make_segment: Callable[..., Segment]) -> tuple[RingStorage, Segment, Segment]:
    ring = RingStorage(buffer_duration_ns=100 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    ring.add(s0)
    ring.add(s1)
    return ring, s0, s1


def test_snapshot_returns_current_segments(make_segment: Callable[..., Segment]) -> None:
    ring, s0, s1 = _ring_with_two(make_segment)
    with ring.snapshot() as lease:
        assert lease.segments == (s0, s1)


def test_snapshot_is_immutable_after_add(make_segment: Callable[..., Segment]) -> None:
    ring, s0, s1 = _ring_with_two(make_segment)
    lease = ring.snapshot()
    ring.add(make_segment(2, 4 * SECOND, 6 * SECOND))
    try:
        assert lease.segments == (s0, s1)
    finally:
        lease.release()


def test_snapshot_pins_and_defers_deletion(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    ring.add(s0)
    ring.add(s1)

    lease = ring.snapshot()  # pins s0 and s1
    ring.add(make_segment(2, 4 * SECOND, 6 * SECOND))  # cutoff = 2s -> s0 expires

    assert s0.path.exists()  # pinned, so not deleted
    assert s0 not in ring.segments  # but excluded from the active ring
    assert s1 in ring.segments

    lease.release()
    assert not s0.path.exists()


def test_snapshot_excludes_expired_segments(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    s2 = make_segment(2, 4 * SECOND, 6 * SECOND)
    ring.add(s0)
    ring.add(s1)
    ring.add(s2)  # s0 expires (unpinned) and is deleted

    with ring.snapshot() as lease:
        assert s0 not in lease.segments
        assert lease.segments == (s1, s2)


def test_multiple_leases_keep_file_until_last_release(
    make_segment: Callable[..., Segment],
) -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    ring.add(s0)
    ring.add(s1)

    lease_a = ring.snapshot()
    lease_b = ring.snapshot()
    ring.add(make_segment(2, 4 * SECOND, 6 * SECOND))  # s0 expires while pinned twice

    lease_a.release()
    assert s0.path.exists()  # still pinned by lease_b

    lease_b.release()
    assert not s0.path.exists()


def test_empty_snapshot_is_allowed() -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    with ring.snapshot() as lease:
        assert lease.segments == ()
    assert lease.released


def test_double_release_is_safe(make_segment: Callable[..., Segment]) -> None:
    ring, _s0, _s1 = _ring_with_two(make_segment)
    lease = ring.snapshot()
    lease.release()
    lease.release()
    assert lease.released
    # The segments are still fine (no negative pin counts).
    assert ring.segment_count == 2


def test_release_is_idempotent_and_segments_remain_readable(
    make_segment: Callable[..., Segment],
) -> None:
    ring, s0, s1 = _ring_with_two(make_segment)
    lease = ring.snapshot()
    lease.release()
    assert lease.segments == (s0, s1)


def test_context_manager_releases_on_exception(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=4 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    ring.add(s0)
    ring.add(s1)

    class BoomError(Exception):
        pass

    with pytest.raises(BoomError):
        with ring.snapshot():
            raise BoomError

    # The lease was released, so the next retention can delete s0.
    ring.add(make_segment(2, 4 * SECOND, 6 * SECOND))
    assert not s0.path.exists()


def test_clear_respects_active_lease(make_segment: Callable[..., Segment]) -> None:
    ring = RingStorage(buffer_duration_ns=100 * SECOND)
    s0 = make_segment(0, 0, 2 * SECOND)
    s1 = make_segment(1, 2 * SECOND, 4 * SECOND)
    ring.add(s0)
    ring.add(s1)

    lease = ring.snapshot()
    ring.clear()

    assert ring.segments == ()
    assert s0.path.exists()
    assert s1.path.exists()

    lease.release()
    assert not s0.path.exists()
    assert not s1.path.exists()


def test_clear_without_lease_deletes_everything(make_segment: Callable[..., Segment]) -> None:
    ring, s0, s1 = _ring_with_two(make_segment)
    ring.clear()
    assert not s0.path.exists()
    assert not s1.path.exists()
    assert ring.duration_ns == 0
