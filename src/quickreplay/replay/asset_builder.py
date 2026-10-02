"""Build a single-file replay asset from a frozen replay snapshot.

:class:`ReplayAssetBuilder` stream-copies the finalized segments of a
:class:`~quickreplay.replay.models.ReplaySnapshot` into one MKV.  It does not
decode, encode or touch the source segment files, and it does not own ring
storage: the caller keeps a snapshot lease alive while :meth:`build` runs.

The output is published atomically.  The remux writes ``replay.tmp.mkv`` and a
successful build replaces ``replay.mkv`` with it via :func:`os.replace`, so an
existing completed asset is never overwritten with an incomplete one.
"""

import os
from pathlib import Path

from quickreplay.recording.models import Segment
from quickreplay.replay.errors import (
    EmptyReplaySnapshotError,
    ReplaySegmentError,
)
from quickreplay.replay.models import ReplayAsset, ReplaySnapshot
from quickreplay.replay.remux import Remux, remux_segments, validate_segment_layouts

REPLAY_FILENAME = "replay.mkv"
"""File name of a completed replay asset."""

REPLAY_TMP_FILENAME = "replay.tmp.mkv"
"""Temporary file name used while a replay asset is being built."""


class ReplayAssetBuilder:
    """Turn a :class:`ReplaySnapshot` into a stream-copied ``replay.mkv``."""

    def __init__(self, *, remux: Remux | None = None) -> None:
        self._remux: Remux = remux or remux_segments

    def build(self, snapshot: ReplaySnapshot, output_directory: Path) -> ReplayAsset:
        """Build the replay asset in *output_directory* and return its metadata.

        The snapshot's segments are only read; they are never modified or
        deleted.  On failure no partial ``replay.mkv`` is published and any
        temporary file is removed.
        """
        segments = snapshot.segments
        _validate_snapshot(segments)
        validate_segment_layouts(segments)

        output_directory = Path(output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        final_path = output_directory / REPLAY_FILENAME
        tmp_path = output_directory / REPLAY_TMP_FILENAME

        try:
            self._remux(segments, tmp_path)
            os.replace(tmp_path, final_path)
        except BaseException:
            _remove_quietly(tmp_path)
            raise

        duration_ns = segments[-1].session_end_ns - segments[0].session_start_ns
        return ReplayAsset(
            path=final_path,
            duration_ns=duration_ns,
            fps=snapshot.stream_info.video.fps,
        )


def _validate_snapshot(segments: tuple[Segment, ...]) -> None:
    if not segments:
        raise EmptyReplaySnapshotError("replay snapshot contains no segments")
    previous: Segment | None = None
    for segment in segments:
        if segment.duration_ns < 0:
            raise ReplaySegmentError(f"segment {segment.id} has a negative duration")
        if not segment.path.exists():
            raise ReplaySegmentError(f"segment file does not exist: {segment.path}")
        if previous is not None:
            if segment.id <= previous.id:
                raise ReplaySegmentError(
                    f"segment id {segment.id} is not greater than the previous id {previous.id}"
                )
            if segment.session_start_ns != previous.session_end_ns:
                raise ReplaySegmentError(
                    f"segment {segment.id} start {segment.session_start_ns} does not continue "
                    f"the previous end {previous.session_end_ns}"
                )
        previous = segment


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
