# Copyright (c) 2022 Nanahuse
# This software is released under the MIT License
# https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE

import queue
from typing import List, Tuple
import cv2
from threading import Thread
import os


class RingCounter(object):
    def __init__(self, max: int, min: int = 0):
        self._counter_max = max
        self._counter_min = min
        self._counter = 0

    def increment(self, diff: int = 1) -> None:
        self._counter += diff

    def decrement(self, diff: int = -1) -> None:
        self._counter += diff

    def __getitem__(self, index: int):
        return (index + self._counter) % (self._counter_max - self._counter_min) + self._counter_min


class RingVideoWriter(object):
    class BufferOverflowException(Exception):
        pass

    class Param(object):
        def __init__(self, fmt: cv2.VideoWriter_fourcc, frame_rate: float, frame_size: Tuple[int, int]):
            self.fmt = fmt
            self.frame_rate = frame_rate
            self.frame_size = frame_size

    def __init__(
        self,
        file_list: List[str],
        fmt: cv2.VideoWriter_fourcc,
        frame_rate: float,
        frame_size: Tuple[int, int],
        file_length_max: int = 10,
        max_buffer_num: int = 60,
    ):
        self._buffer = queue.Queue(maxsize=max_buffer_num)
        self._file_frame_max = int(frame_rate * file_length_max)
        self._file_list = file_list
        self._writer = cv2.VideoWriter(file_list[0], fmt, frame_rate, frame_size)
        self._param = RingVideoWriter.Param(fmt, frame_rate, frame_size)
        self._writer_thread = Thread(target=self._writer_task)
        self._counter = RingCounter(len(file_list))
        self._is_run = True
        self._writer_thread.start()

    def write(self, frame: cv2.Mat) -> None:
        try:
            self._buffer.put_nowait(frame)
        except queue.Full:
            raise RingVideoWriter.BufferOverflowException(f"overflow -> buffer max : {self._buffer.maxsize}")

    def release(self) -> List[str]:
        if self._is_run:
            self._is_run = False
            self._writer_thread.join()
            self._writer.release()
        return [self._file_list[self._counter[i + 1]] for i in range(len(self._file_list))]

    def _writer_task(self) -> None:
        counter = 0
        while True:
            try:
                frame = self._buffer.get(timeout=0.5)
                self._writer.write(frame)
                counter += 1
                if counter >= self._file_frame_max:
                    counter = 0
                    self._counter.increment()
                    self._writer = cv2.VideoWriter(
                        self._file_list[self._counter[0]],
                        self._param.fmt,
                        self._param.frame_rate,
                        self._param.frame_size,
                    )
            except queue.Empty:
                if self._is_run is False:
                    break


class RingVideoCapture(object):
    class _Capture:
        def __init__(self, file_path: str):
            self.capture = cv2.VideoCapture(file_path)
            self.frame_num = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))

    def __init__(self, file_list: List[str]):
        self._caps = [RingVideoCapture._Capture(file) for file in file_list if os.path.exists(file)]
        self._cap_cursor = 0
        self._frame_cursor = 0
        self._frame_num = sum([cap.frame_num for cap in self._caps])

    def release(self) -> None:
        for cap in self._caps:
            cap.capture.release()

    def read(self) -> cv2.Mat:
        tmp_cap = self._caps[self._cap_cursor]
        _, frame = tmp_cap.capture.read()
        if self._frame_cursor < tmp_cap.frame_num:
            self._frame_cursor += 1
        if self._frame_cursor >= tmp_cap.frame_num:
            if self._cap_cursor != len(self._caps) - 1 and self._caps[self._cap_cursor + 1].frame_num != 0:
                self._cap_cursor += 1
                self._frame_cursor = 0
        return frame

    def move_first(self) -> None:
        # 0フレーム目に移動
        self._cap_cursor = 0
        self._frame_cursor = 0
        self._caps[0].capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def move_last(self) -> None:
        # 最終フレームへ移動
        for i, cap in enumerate(self._caps[-1::-1]):
            if cap.frame_num != 0:
                self._cap_cursor = len(self._caps) - 1 - i
                break
        self._frame_cursor = self._caps[self._cap_cursor].frame_num - 1
        self._caps[self._cap_cursor].capture.set(cv2.CAP_PROP_POS_FRAMES, self._frame_cursor)

    def move_diff(self, diff: int) -> None:
        self._frame_cursor += diff
        if diff < 0:
            if self._cap_cursor != 0:
                for i, cap in enumerate(self._caps[self._cap_cursor - 1 :: -1]):
                    if self._frame_cursor >= 0:
                        self._cap_cursor -= i
                        self._caps[self._cap_cursor].capture.set(cv2.CAP_PROP_POS_FRAMES, self._frame_cursor)
                        return
                    else:
                        self._frame_cursor += cap.frame_num

            # self._cap_cursor == 0になったときの処理
            if self._frame_cursor < 0:
                self.move_first()
                return
            else:
                self._cap_cursor = 0  # self._cap_cursor = 0と実質同じ
                self._caps[self._cap_cursor].capture.set(cv2.CAP_PROP_POS_FRAMES, self._frame_cursor)
                return

        elif diff > 0:
            for i, cap in enumerate(self._caps[self._cap_cursor : :]):
                if self._frame_cursor < cap.frame_num:
                    self._cap_cursor += i
                    self._caps[self._cap_cursor].capture.set(cv2.CAP_PROP_POS_FRAMES, self._frame_cursor)
                    return
                else:
                    self._frame_cursor -= cap.frame_num
            else:
                self.move_last()

    def move_frame(self, frame_num: int) -> None:
        # 指定のフレームに移動する。
        # 範囲オーバーの場合もエラーにならず端で止まる
        self.move_first()
        self.move_diff(frame_num)

    def get_frame_num(self) -> int:
        return self._frame_num

    def get_now_frame(self) -> int:
        # cv2.VideoCaptureは読み込んだフレームの次のフレームにカーソルがあった状態になるため内部的には1ずらした状態になるが、
        # 使用する際には直前に読み込んだフレームの数字が表示された方が便利なので1マイナスしている。
        frame_cursor = 0
        if self._cap_cursor > 0:
            for cap in self._caps[: self._cap_cursor :]:
                frame_cursor += cap.frame_num

        frame_cursor += self._frame_cursor
        return frame_cursor - 1
