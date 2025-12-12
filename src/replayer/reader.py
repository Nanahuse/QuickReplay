from collections.abc import Generator

from cv2.typing import MatLike

from .capture_wrapper import CaptureWrapper


class Iterator:
    def __init__(self, captures: list[CaptureWrapper]) -> None:
        self._captures: list[CaptureWrapper] = captures

        self._current_file_index: int = 0

    def next(self) -> None:
        if self.is_last():
            return
        self._current_file_index += 1

    def prev(self) -> None:
        if self.is_first():
            return
        self._current_file_index -= 1

    @property
    def capture(self) -> CaptureWrapper:
        return self._captures[self._current_file_index]

    def is_first(self) -> bool:
        return self._current_file_index == 0

    def is_last(self) -> bool:
        return self._current_file_index == len(self._captures) - 1

    def walk_to_last(self) -> Generator[CaptureWrapper]:
        while not self.is_last():
            yield self.capture
            self.next()
        yield self.capture

    def walk_to_first(self) -> Generator[CaptureWrapper]:
        while not self.is_first():
            yield self.capture
            self.prev()
        yield self.capture

    def first_to_current(self) -> Generator[CaptureWrapper]:
        yield from self._captures[: self._current_file_index]


class Reader:
    def __init__(self, captures: list[CaptureWrapper]) -> None:
        self._captures: list[CaptureWrapper] = captures
        self._iterator: Iterator = Iterator(captures)

    def read(self) -> MatLike | None:
        while True:
            frame = self._iterator.capture.read()

            if frame is not None:
                if self._iterator.capture.has_reached_end():
                    self._iterator.next()
                return frame

            if not self._iterator.capture.has_reached_end():
                return None

            if self._iterator.is_last():
                return None

            self._iterator.next()

    def read_prev(self) -> MatLike | None:
        if self.has_reached_begin():
            return None
        self.move_diff(-1)
        frame = self.read()
        self.move_diff(-1)
        return frame

    def move_first(self) -> None:
        for cap in self._iterator.walk_to_first():
            cap.move_first()

    def move_end(self) -> None:
        for cap in self._iterator.walk_to_last():
            cap.move_end()

    def move_diff(self, frame_num: int) -> None:
        if frame_num == 0:
            return

        remain = frame_num
        generator = self._iterator.walk_to_last() if frame_num > 0 else self._iterator.walk_to_first()
        for cap in generator:
            remain = cap.move_diff(remain)
            if remain == 0:
                break

    def frame_count(self) -> int:
        return sum(cap.frame_count() for cap in self._captures)

    def current_frame(self) -> int:
        return sum(cap.frame_count() for cap in self._iterator.first_to_current()) + self._iterator.capture.cursor()

    def has_reached_begin(self) -> bool:
        return self._iterator.is_first() and self._iterator.capture.cursor() == 0

    def has_reached_end(self) -> bool:
        return self._iterator.is_last() and self._iterator.capture.has_reached_end()
