from datetime import UTC, datetime, timedelta
from enum import Enum
from queue import Queue

import cv2

from .file_manager import FileManager
from .reader import Reader
from .utils import open_captures


class Mode(Enum):
    STOP = "stop"
    PAUSE = "pause"
    PLAY = "play"
    NEXT = "next"
    PREV = "prev"
    SKIP_FORWARD = "skip_forward"
    SKIP_BACK = "skip_back"


class Replayer:
    def __init__(
        self,
        file_manager: FileManager,
        window_name: str,
        frame_rate: int,
        skip_seconds: int = 5,
    ) -> None:
        self._file_manager: FileManager = file_manager
        self._window_name: str = window_name
        self._frame_rate: int = frame_rate
        self._skip_frame_num: int = skip_seconds * frame_rate
        self._mode_queue: Queue[Mode] = Queue()

    def send_command(self, mode: Mode) -> None:
        self._mode_queue.put(mode)

    def _play(self, reader: Reader) -> None:
        frame_delta = timedelta(seconds=1.0 / self._frame_rate)
        last_update_time = datetime.now(tz=UTC)
        while self._mode_queue.empty():
            frame = reader.read()

            if frame is not None:
                cv2.imshow(self._window_name, frame)
                time = datetime.now(tz=UTC)

                wait_time = last_update_time + frame_delta - time
                last_update_time = time
                cv2.waitKey(max(int(wait_time.total_seconds() * 1000), 0))

            if reader.has_reached_end():
                break

    def _next(self, reader: Reader) -> None:
        frame = reader.read()
        if frame is not None:
            cv2.imshow(self._window_name, frame)
            cv2.waitKey(0)

    def _prev(self, reader: Reader) -> None:
        frame = reader.read_prev()
        if frame is not None:
            cv2.imshow(self._window_name, frame)
            cv2.waitKey(0)

    def _skip_forward(self, reader: Reader) -> None:
        reader.move_diff(self._skip_frame_num)
        frame = reader.read()
        if frame is not None:
            cv2.imshow(self._window_name, frame)
            cv2.waitKey(0)

    def _skip_back(self, reader: Reader) -> None:
        reader.move_diff(-self._skip_frame_num + 1)
        frame = reader.read()
        if frame is not None:
            cv2.imshow(self._window_name, frame)
            cv2.waitKey(0)

    def run(self) -> None:
        mode = Mode.PAUSE

        with open_captures(self._file_manager.files()) as captures:
            reader = Reader(captures)

            while True:
                mode = self._mode_queue.get()

                match mode:
                    case Mode.STOP:
                        return
                    case Mode.PAUSE:
                        pass  # Do nothing until next command
                    case Mode.PLAY:
                        self._play(reader)
                    case Mode.NEXT:
                        self._next(reader)
                    case Mode.PREV:
                        self._prev(reader)
                    case Mode.SKIP_FORWARD:
                        self._skip_forward(reader)
                    case Mode.SKIP_BACK:
                        self._skip_back(reader)
