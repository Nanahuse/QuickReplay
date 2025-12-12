import cv2
from cv2.typing import MatLike


class CaptureWrapper:
    def __init__(self, capture: cv2.VideoCapture) -> None:
        self._capture: cv2.VideoCapture = capture

        self._frame_num = int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self._cursor: int = 0

    def is_opened(self) -> bool:
        return self._capture.isOpened()

    def frame_count(self) -> int:
        return self._frame_num

    def cursor(self) -> int:
        return self._cursor

    def has_reached_end(self) -> bool:
        return self._cursor == self._frame_num

    def read(self) -> MatLike | None:
        if self.has_reached_end():
            return None

        self._cursor += 1
        _, frame = self._capture.read()
        return frame

    def move_first(self) -> None:
        self._cursor = 0
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def move_last(self) -> None:
        self._cursor = self._frame_num - 1
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, self._cursor)

    def move_end(self) -> None:
        self._cursor = self._frame_num
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)  # set to 0 to avoid issues

    def move_diff(self, diff: int) -> int:
        self._cursor += diff
        if self._cursor < 0:
            remain = self._cursor
            self.move_first()
            return remain
        if self._cursor >= self._frame_num:
            remain = self._cursor - self._frame_num
            self.move_end()
            return remain

        self._capture.set(cv2.CAP_PROP_POS_FRAMES, self._cursor)
        return 0
