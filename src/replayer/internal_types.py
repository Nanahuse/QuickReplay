from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from windows_capture_device_list import Resolution as WinResolution

FourCC = int


@dataclass
class Resolution:
    x: int
    y: int

    def to_string(self) -> str:
        return f"{self.x} x {self.y}"

    @staticmethod
    def from_string(s: str) -> Resolution:
        x_str, y_str = s.split(" x ")
        return Resolution(int(x_str), int(y_str))

    def to_tuple(self) -> tuple[int, int]:
        return (self.x, self.y)

    @staticmethod
    def from_win_resolution(res: WinResolution) -> Resolution:
        return Resolution(res.width, res.height)


@dataclass
class CaptureDevice:
    device_num: int
    name: str
    resolution: list[Resolution]
