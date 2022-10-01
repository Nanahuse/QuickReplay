# Copyright (c) 2022 Nanahuse
# This software is released under the MIT License
# https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE

from inspect import getmembers


def tkvar_to_dict(setting) -> dict:  # NOQA
    return_dict = {}
    for method in getmembers(setting):
        if "__" in method[0]:
            continue
        if hasattr(method[1], "get"):
            return_dict[method[0]] = method[1].get()
    return return_dict


def tkvar_from_dict(input_dict, output) -> None:  # NOQA
    for method in getmembers(output):
        if hasattr(method[1], "set"):
            if method[0] in input_dict:
                method[1].set(input_dict[method[0]])


if __name__ == "__main__":
    import tkinter as tk
    from dataclasses import dataclass

    @dataclass
    class SettingReplay(object):
        length: tk.IntVar
        auto_restart: tk.IntVar

    frame = tk.Frame()
    replay = SettingReplay(tk.IntVar(frame), tk.IntVar(frame))

    replay.length.set(100)
    replay.auto_restart.set(120)

    tmp = tkvar_to_dict(replay)
    print(tmp)

    tmp["length"] = -10
    tmp["auto_restart"] = 200
    replay = SettingReplay(tk.IntVar(frame), tk.IntVar(frame))
    tkvar_from_dict(tmp, replay)
    print(replay.length.get())
    print(replay.auto_restart.get())
