from dataclasses import dataclass


@dataclass(frozen=True)
class Resolution(object):
    x: int
    y: int

    def __str__(self) -> str:
        return f"{self.x} x {self.y}"
