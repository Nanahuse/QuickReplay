# Copyright (c) 2022 Nanahuse
# This software is released under the GPLv3 License.
# https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE

from __future__ import annotations

import contextlib
import queue
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Self

import cv2

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import TracebackType

    from cv2.typing import MatLike

    from .file_manager import FileManager
    from .internal_types import FourCC, Resolution

DEFAULT_MAX_BUFFER_LENGTH_SECOND: int = 60


class Writer:
    def __init__(
        self,
        file_manager: FileManager,
        fmt: FourCC,
        frame_rate: int,
        frame_size: Resolution,
        max_buffer_seconds: int = DEFAULT_MAX_BUFFER_LENGTH_SECOND,
    ) -> None:
        self._file_manager: FileManager = file_manager
        self._fmt: FourCC = fmt
        self._frame_rate: int = frame_rate
        self._frame_size: Resolution = frame_size
        self._max_buffer_seconds: int = max_buffer_seconds

        self._buffer: queue.Queue[MatLike] = queue.Queue()
        self._release_event: Event = Event()
        self._max_buffer_length: int = self._frame_rate * self._max_buffer_seconds
        self._writer_thread: Thread = Thread(target=self._write_task)

    def __enter__(self) -> Self:
        self._writer_thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._release_event.set()
        self._writer_thread.join()

    def is_running(self) -> bool:
        return not self._release_event.is_set()

    def write(self, frame: MatLike) -> None:
        if self.is_running():
            self._buffer.put(frame)

    def _processing_required(self) -> bool:
        return self.is_running() or not self._buffer.empty()

    def _write_task(self) -> None:
        while self._processing_required():
            path = self._file_manager.get_new_file_path()
            counter = 0
            with self._open_cv2_writer(path) as writer:
                while self._processing_required() and counter < self._max_buffer_length:
                    try:
                        frame = self._buffer.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    writer.write(frame)
                    counter += 1
            self._file_manager.push_file(Path(path), counter)

    @contextlib.contextmanager
    def _open_cv2_writer(self, file_path: Path) -> Generator[cv2.VideoWriter]:
        writer = cv2.VideoWriter(str(file_path), self._fmt, self._frame_rate, self._frame_size.to_tuple())

        try:
            yield writer

        finally:
            writer.release()
            del writer
