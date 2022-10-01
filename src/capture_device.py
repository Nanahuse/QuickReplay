# Copyright (c) 2022 Nanahuse
# This software is released under the MIT License
# https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE


from dataclasses import dataclass
from typing import List

import device  # https://github.com/yushulx/python-capture-device-list


@dataclass
class Resolution(object):
    x: int
    y: int

    def to_string(self) -> str:
        return f"{self.x} x {self.y}"


@dataclass
class CaptureDevice(object):
    device_num: int
    name: str
    resolution: List[Resolution]


def get_devices() -> List[CaptureDevice]:
    try:
        device_list = device.getDeviceList()
    except:
        # デバッグ実行時にエラーになってしまうため
        device_list = [
            ("これはサンプルです", [(1920, 1080), (1280, 720), (960, 540), (640, 360)]),
            ("Debug2", [(1920, 1080), (1280, 720), (960, 540)]),
            ("Debug3", [(1920, 1080), (1280, 720), (640, 360)]),
            ("Debug4", [(960, 540), (640, 360)]),
            ("Debug5", [(1920, 1080), (1280, 720), (960, 540)]),
            ("Debug6", [(1920, 1080), (1280, 720), (960, 540)]),
        ]

    return [
        CaptureDevice(
            device_num,
            capture_device[0],
            [Resolution(resolution[0], resolution[1]) for resolution in capture_device[1]],
        )
        for device_num, capture_device in enumerate(device_list)
    ]
