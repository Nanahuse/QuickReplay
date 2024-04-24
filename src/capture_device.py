# Copyright (c) 2022 Nanahuse
# This software is released under the MIT License
# https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE


from dataclasses import dataclass

import device

from resolution import Resolution


@dataclass(frozen=True)
class CaptureDevice(object):
    device_num: int
    name: str
    resolution: tuple[Resolution, ...]


def get_devices() -> tuple[CaptureDevice, ...]:
    device_list = device.getDeviceList()

    return tuple(
        CaptureDevice(
            device_num,
            capture_device[0],
            tuple(Resolution(resolution[0], resolution[1]) for resolution in capture_device[1]),
        )
        for device_num, capture_device in enumerate(device_list)
    )


if __name__ == "__main__":
    print(get_devices())
