# Copyright (c) 2022 Nanahuse
# This software is released under the MIT License
# https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE

from contextlib import contextmanager
from enum import Enum, auto
import json
import os
from queue import Queue
from time import sleep, time
from threading import Thread
import tkinter as tk
from typing import Callable, List, Optional
import webbrowser

import cv2
import ttkbootstrap as ttk

from dataclasses import dataclass
from quick_replay_view import SettingView, ReplayerView, InfoView
from utils import tkvar_from_dict, tkvar_to_dict
from ring_video import RingVideoWriter, RingVideoCapture
from capture_device import get_devices

FILE_LENGTH = 60  # 秒数
FMT = cv2.VideoWriter_fourcc("m", "p", "4", "v")
WRITER_BUFFER_SIZE = 60  # フレーム数

VIDEO_FOLDER_PATH = "./tmp_video/"
VIDEO_NAME_PREFIX = "output"
VIDEO_NAME_EXTENSION = ".mp4"


class Model(object):
    @dataclass
    class VarSettingWebcamera(object):
        input_device: tk.StringVar
        resolution: tk.StringVar
        frame_rate: tk.IntVar

    @dataclass
    class VarSettingReplay(object):
        length: tk.IntVar
        auto_restart: tk.IntVar
        recording_preview: tk.BooleanVar

    @dataclass
    class UserSettings(object):
        device_name: str
        device_num: int
        frame_rate: int
        width: int
        height: int
        replay_time: int
        replay_time: int
        auto_restart: int
        recording_preview: bool

    @dataclass
    class RingVideoWriterSetting(object):
        fmt: cv2.VideoWriter_fourcc
        file_length_max: int
        buffer_size_max: int


class ModeState(Enum):
    PAUSE = auto()
    PLAY = auto()
    RECORDING = auto()


@contextmanager
def open_cv2VideoCapture(device_num: int, width: int, height: int) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(device_num, cv2.CAP_DSHOW)
    if capture.isOpened():
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        try:
            yield capture
        finally:
            capture.release()


@contextmanager
def open_RingVideoCapture(file_list: List[str]) -> RingVideoCapture:
    player = RingVideoCapture(file_list)
    try:
        yield player
    finally:
        player.release()


@contextmanager
def open_RingVideoWriter(
    file_list: List[str],
    user_settings: Model.UserSettings,
    writer_settins: Model.RingVideoWriterSetting,
    file_list_callback: Callable[[List[str]], None],
) -> RingVideoWriter:
    writer = RingVideoWriter(
        file_list,
        writer_settins.fmt,
        user_settings.frame_rate,
        (user_settings.width, user_settings.height),
        writer_settins.file_length_max,
        writer_settins.buffer_size_max,
    )
    try:
        yield writer
    finally:
        files = writer.release()
        file_list_callback(files)


class Cv2Display(object):
    # cv2.imshowはメインスレッドでないと動作しないため、
    # 描写関数をtkinter.Window.afterに登録し、メインスレッドで実行する
    def __init__(self, root: ttk.Window, window_name: str):
        self.window_name = window_name
        self.queue = Queue()
        self.root = root
        self.id = None

    def is_working(self) -> None:
        return self.id is not None

    def start(self) -> None:
        self.id = self.root.after(5, self.show)

    def stop(self) -> None:
        if self.is_working():
            self.root.after_cancel(self.id)
            self.id = None
            self.root.after(5, self.close_window)

    def set_frame(self, frame: cv2.Mat) -> None:
        if self.is_working():
            self.queue.put_nowait(frame)

    def show(self) -> None:
        try:
            while True:
                frame = self.queue.get_nowait()
                cv2.imshow(self.window_name, frame)
                cv2.waitKey(1)
        except:
            # 描写するフレームがない場合
            pass
        self.id = self.root.after(5, self.show)

    def close_window(self) -> None:
        try:
            cv2.destroyWindow(self.window_name)
        except:
            # windowが存在しなかった場合
            pass


class Repeater(object):
    """
    start後、cancelされるまでintervalの間隔で関数を実行し続ける。
    """

    def __init__(self, root: ttk.Window, function: Callable[[None], None], repeatdelay: int, repeatinterval: int):
        self.root = root
        self.function = function
        self.repeatdelay = repeatdelay
        self.repeatinterval = repeatinterval
        self.id = None

    def cancel(self, event) -> None:  # NOQA
        if self.id is not None:
            self.root.after_cancel(self.id)
            self.id = None

    def start(self, event) -> None:  # NOQA
        # 開始とともに一回実行する。
        self.function()
        self.id = self.root.after(self.repeatdelay, self._repeat_function)

    def _repeat_function(self) -> None:
        # キャンセルされるまで一定時間ごとに実行され続ける
        self.function()
        self.id = self.root.after(self.repeatinterval, self._repeat_function)


class ReplayerModel(object):
    def __init__(
        self,
        file_list: List[str],
        frame_rate: int,
        counter_callback: Callable[[int, float], None],
        display: Cv2Display,
        fast_diff: int,
    ):
        self.frame_rate = frame_rate
        self.counter_callback = lambda frame_num: counter_callback(frame_num, self.frame_to_time(frame_num))
        self.capture = RingVideoCapture(file_list)
        self.fast_diff = fast_diff
        self.is_playing = False
        self.play_thread: Optional[Thread] = None
        self.display = display

        self.play_stop: Thread = None

        self.to_last()

    def release(self) -> None:
        self.capture.release()

    def to_first(self) -> None:
        self.capture.move_first()
        self.prev_frame()

    def to_last(self) -> None:
        self.capture.move_last()
        self.next_frame()

    def next_frame(self) -> None:
        frame = self.capture.read()
        self.counter_callback(self.capture.get_now_frame())
        if frame is not None:
            self.display.set_frame(frame)

    def prev_frame(self) -> None:
        self.capture.move_diff(-2)
        frame = self.capture.read()
        self.counter_callback(self.capture.get_now_frame())
        if frame is not None:
            self.display.set_frame(frame)

    def fast_foward(self) -> None:
        self.capture.move_diff(self.fast_diff - 1)
        frame = self.capture.read()
        self.counter_callback(self.capture.get_now_frame())
        if frame is not None:
            self.display.set_frame(frame)

    def rewind(self) -> None:
        self.capture.move_diff(-self.fast_diff - 1)
        frame = self.capture.read()
        self.counter_callback(self.capture.get_now_frame())
        if frame is not None:
            self.display.set_frame(frame)

    def move_to(self, frame_num: int) -> None:
        self.capture.move_frame(frame_num)
        frame = self.capture.read()
        if frame is not None:
            self.display.set_frame(frame)

    def start_play(self, play_stop_callback: Callable[[None], None]) -> None:
        if not self.is_playing:
            self.is_playing = True
            self.play_thread = Thread(target=self._work_play, args=(play_stop_callback,))
            self.play_thread.start()

    def stop_play(self) -> None:
        self.is_playing = False
        if self.play_thread is not None:
            self.play_thread = None

    def _work_play(self, play_stop_callback: Callable[[None], None]) -> None:
        start_time = time()
        i = 1
        counter = 0
        while self.is_playing:
            tmp = i / self.frame_rate
            tmp_time = time()
            if tmp_time < start_time + tmp:
                counter += 1
                sleep(start_time + tmp - tmp_time)
            frame = self.capture.read()
            self.counter_callback(self.capture.get_now_frame())
            if frame is not None:
                self.display.set_frame(frame)
            else:
                self.is_playing = False
            i += 1
        play_stop_callback()

    def frame_to_time(self, frame_counter: int) -> float:
        return round((frame_counter) / self.frame_rate, 3)


class RecorderModel(object):
    def __init__(
        self,
        file_list: List[str],
        user_settings: Model.UserSettings,
        writer_settings: Model.RingVideoWriterSetting,
        display: Cv2Display,
    ):
        self.file_list = [file for file in file_list]
        self.user_settings = user_settings
        self.writer_settings = writer_settings
        self.is_recording = False
        self._recording_thread: Optional[Thread] = None
        self.display = display

    def get_file_list(self) -> List[str]:
        return self.file_list

    def get_frame_rate(self) -> int:
        return self.user_settings.frame_rate

    def start(self) -> None:
        if not self.is_recording:
            if self.user_settings.recording_preview is False:
                self.display.stop()
            self.is_recording = True
            self._recording_thread = Thread(target=self._work_recording)
            self._recording_thread.start()

    def stop(self) -> None:
        if self.is_recording:
            self.is_recording = False
            while self._recording_thread.is_alive():
                sleep(0.1)
            self._recording_thread = None
            self.display.start()

    def _work_recording(self) -> None:
        with open_cv2VideoCapture(
            self.user_settings.device_num, self.user_settings.width, self.user_settings.height
        ) as capture:
            writer = RingVideoWriter
            with open_RingVideoWriter(
                self.file_list, self.user_settings, self.writer_settings, self.update_file_list
            ) as writer:
                while self.is_recording:
                    _, frame = capture.read()
                    if frame is not None:
                        writer.write(frame)
                        self.display.set_frame(frame)

    def update_file_list(self, file_list: List[str]) -> None:
        self.file_list = file_list


class _ControllerBase(object):
    def __init__(self) -> None:
        pass

    def enable(self) -> None:
        # 画面を有効にする
        pass

    def disable(self) -> None:
        # 画面を無効にする
        pass


class _InfomationWindow(object):
    def __init__(self, root):
        self.is_alive = False
        self.root = root

    def show_window(self) -> None:
        if self.is_alive:
            return
        self.is_alive = True

        self.window = ttk.Toplevel(self.root, resizable=(False, False))
        self.window.title("Infomation")

        self.info_frame = InfoView(self.window)
        self.license_link_button_commands: List[Callable[[None], None]] = []

        with open("./assets/software_infomation.json", encoding="UTF-8") as f:
            infomation = json.load(f)
            info_string = "\n".join([f"{tmp}\t: {infomation[tmp]}" for tmp in ["Name", "Auther", "Version", "License"]])
            self.info_frame.info_label.configure(text=info_string)
            self.info_frame.github_link_button.configure(
                command=lambda infomation=infomation: webbrowser.open(infomation["URL"])
            )  # infomation=infomationで実行時ではなく宣言時の値を使用するようにしている
            self.info_frame.license_link_button.configure(
                command=lambda infomation=infomation: webbrowser.open(infomation["License_URL"])
            )

        with open("./assets/LICENSE_ThirdParty.json", encoding="UTF-8") as f:
            licenses = json.load(f)

            for tmp_license in licenses:
                button = self.info_frame.license_frame.add(tmp_license["Name"], tmp_license["License"])
                button.configure(
                    command=lambda tmp_license=tmp_license: webbrowser.open(tmp_license["Link"])
                )  # tmp_license=tmp_licenseで実行時ではなく宣言時の値を使用するようにしている

        self.info_frame.enable()
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        self.is_alive = False
        self.window.destroy()


class _SettingController(_ControllerBase):
    def __init__(self, root, press_start_callback: Callable[[None], None]):  # NOQA
        self.root = root
        self.view = SettingView(self.root)

        self.infomation = _InfomationWindow(self.root)

        # 変数のbind
        self.capture_devices = get_devices()
        self.setting_webcamera = Model.VarSettingWebcamera(
            tk.StringVar(self.root), tk.StringVar(self.root), tk.IntVar(self.root)
        )
        self.setting_replay = Model.VarSettingReplay(
            tk.IntVar(self.root), tk.IntVar(self.root), tk.BooleanVar(self.root)
        )

        self.view.webcam_select.configure(textvariable=self.setting_webcamera.input_device)
        self.view.webcam_resolution.configure(textvariable=self.setting_webcamera.resolution)
        self.view.webcam_framerate.configure(textvariable=self.setting_webcamera.frame_rate)
        self.view.replay_length.configure(textvariable=self.setting_replay.length)
        self.view.replay_auto_restart.configure(textvariable=self.setting_replay.auto_restart)

        self.view.webcam_select.configure(values=[device.name for device in self.capture_devices])
        self.view.webcam_select.bind("<<ComboboxSelected>>", self.on_change_device)
        self.view.webcam_resolution.bind("<<ComboboxSelected>>", self.on_change_resolution)

        # ボタン動作のbind
        self.view.button_reset.configure(command=self.load_settings)
        self.view.button_save.configure(command=self.save_settings)
        self.view.button_start.configure(command=press_start_callback)
        self.view.button_info.configure(command=self.press_info)

        # 値が設定されるまでStartボタンを隠す。
        self.view.button_start.configure(state="disable")

        self.load_settings()

    def enable(self) -> None:
        self.view.enable()

    def disable(self) -> None:
        self.view.disable()

    def save_settings(self) -> None:
        save_dist = {}
        save_dist["webcamera"] = tkvar_to_dict(self.setting_webcamera)
        save_dist["replay"] = tkvar_to_dict(self.setting_replay)

        with open("./assets/config.json", "w", encoding="UTF-8") as f:
            json.dump(save_dist, f, indent=4)

    def load_settings(self) -> None:
        try:
            with open("./assets/config.json", "r", encoding="UTF-8") as f:
                json_data = json.load(f)
        except:
            with open("assets/default_setting.json", "r", encoding="UTF-8") as f:
                json_data = json.load(f)

        if json_data["webcamera"]["input_device"] not in [device.name for device in self.capture_devices]:
            json_data["webcamera"]["input_device"] = ""

        tkvar_from_dict(json_data["webcamera"], self.setting_webcamera)
        tkvar_from_dict(json_data["replay"], self.setting_replay)

        self.on_change_device(None)
        # on_change_recording_preveiwを実行すると値が反転してしまうため予め逆にしておく
        self.setting_replay.recording_preview.set(not self.setting_replay.recording_preview.get())
        self.on_change_recording_preview()

    def press_info(self, event=None) -> None:  # NOQA
        self.infomation.show_window()

    def on_change_device(self, event) -> None:  # NOQA
        now_resolution = self.setting_webcamera.resolution.get()

        device_name = self.setting_webcamera.input_device.get()
        for device in self.capture_devices:
            if device.name == device_name:
                self.view.webcam_resolution.configure(
                    values=[resolution.to_string() for resolution in device.resolution]
                )
                for resolution in device.resolution:
                    if resolution.to_string() == now_resolution:
                        self.view.button_start.configure(state="enable")
                        return
                break
        else:
            self.view.webcam_resolution.configure(values=[])

        # 指定解像度に対応してない、または選択肢がないときは空に戻す。
        self.setting_webcamera.resolution.set("")
        self.view.button_start.configure(state="disable")

    def on_change_resolution(self, event=None) -> None:  # NOQA
        now_resolution = self.setting_webcamera.resolution.get()

        # 正しい解像度が設定されるまでStartボタンを隠す処理
        if now_resolution == "":
            self.view.button_start.configure(state="disable")
        else:
            self.view.button_start.configure(state="enable")

    def get_settings(self) -> Model.UserSettings:

        device_name = self.setting_webcamera.input_device.get()
        for device in self.capture_devices:
            if device_name == device.name:
                device_num = device.device_num
                break
        frame_rate = self.setting_webcamera.frame_rate.get()
        resolution = [int(tmp) for tmp in self.setting_webcamera.resolution.get().split("x")]
        replay_time = self.setting_replay.length.get()
        auto_restart = self.setting_replay.auto_restart.get()
        recording_preview = self.setting_replay.recording_preview.get()

        setting = Model.UserSettings(
            device_name=device_name,
            device_num=device_num,
            frame_rate=frame_rate,
            width=resolution[0],
            height=resolution[1],
            replay_time=replay_time,
            auto_restart=auto_restart,
            recording_preview=recording_preview,
        )

        # print(f"カメラ名　　　　: {setting.device_name}")
        # print(f"カメラ番号　　　: {setting.device_num}")
        # print(f"解像度　　　　　: {setting.width}, {setting.height}")
        # print(f"フレームレート　: {setting.frame_rate}")
        # print(f"保存長さ　　　　: {setting.replay_time}")
        # print(f"自動再開　　　　: {setting.auto_restart}")

        return setting

    def on_change_recording_preview(self) -> None:
        flag = not self.setting_replay.recording_preview.get()
        self.setting_replay.recording_preview.set(flag)

        if flag:
            self.view.recording_preview_check_enable.configure(bootstyle="default")
            self.view.recording_preview_check_disable.configure(bootstyle="secondary")

            self.view.recording_preview_check_enable.configure(command=lambda: ())
            self.view.recording_preview_check_disable.configure(command=self.on_change_recording_preview)
        else:
            self.view.recording_preview_check_enable.configure(bootstyle="secondary")
            self.view.recording_preview_check_disable.configure(bootstyle="light")
            self.view.recording_preview_check_enable.configure(command=self.on_change_recording_preview)
            self.view.recording_preview_check_disable.configure(command=lambda: ())


class _ReplayerController(_ControllerBase):
    REPEAT_DELAY = 500
    REPEAT_INTERVAL_FAST = 50
    REPEAT_INTERVAL = 85
    FAST_MOVE_FRAME = 20

    def __init__(self, root: ttk.Window):
        self.root = root
        self.view = ReplayerView(self.root)

        self.var_seekbar = tk.IntVar()
        self.var_frame_counter = tk.StringVar(value="FRAME COUNTER(from the point)")
        self.view.seekbar.configure(variable=self.var_seekbar, command=self.on_seekbar_change)
        self.view.counter_label.configure(textvariable=self.var_frame_counter)

        # ボタンを押しっぱなしのときに繰り返し実行するためのリピーターをかませる。
        self.repeat_rewind = Repeater(self.root, self.press_rewind, self.REPEAT_DELAY, self.REPEAT_INTERVAL_FAST)
        self.repeat_forward = Repeater(self.root, self.press_forward, self.REPEAT_DELAY, self.REPEAT_INTERVAL_FAST)
        self.repeat_prev = Repeater(self.root, self.press_prev, self.REPEAT_DELAY, self.REPEAT_INTERVAL)
        self.repeat_next = Repeater(self.root, self.press_next, self.REPEAT_DELAY, self.REPEAT_INTERVAL)

        # ボタンを押したときの動作
        self.view.button_rewind.bind("<ButtonPress>", self.repeat_rewind.start)
        self.view.button_forward.bind("<ButtonPress>", self.repeat_forward.start)
        self.view.button_prev.bind("<ButtonPress>", self.repeat_prev.start)
        self.view.button_next.bind("<ButtonPress>", self.repeat_next.start)

        # ボタンを離したときの動作
        self.view.button_rewind.bind("<ButtonRelease>", self.repeat_rewind.cancel)
        self.view.button_forward.bind("<ButtonRelease>", self.repeat_forward.cancel)
        self.view.button_prev.bind("<ButtonRelease>", self.repeat_prev.cancel)
        self.view.button_next.bind("<ButtonRelease>", self.repeat_next.cancel)

        self.view.button_set_point.configure(command=self.press_set_point)

        self.display = Cv2Display(self.root, "Quick Replayer View")
        self.display.start()

        self.replayer: Optional[ReplayerModel] = None
        self.recorder: Optional[RecorderModel] = None

        self.origin_point_frame_num: Optional[int] = None

    def enable(self) -> None:
        self.view.enable()
        self._play_stop_callback()
        self.start_recording()

    def disable(self) -> None:
        self.view.disable()
        raise NotImplementedError()

    def start_recording(self) -> None:
        if self.mode == ModeState.PLAY:
            self.replayer.stop_play()

        if self.replayer is not None:
            self.replayer.release()

        if self.recorder is None:
            # FIXME:ERROR DIALOG
            return

        self.mode = ModeState.RECORDING
        self.change_widget_state_for_recording(False)
        self.view.button_recording.configure(image=self.view.icon_stop, command=self.stop_recording, bootstyle="danger")
        self.view.seekbar_right_label.configure(text="Recording")
        self.view.seekbar.configure(from_=-1, to=0, value=0, state="disable")
        self.reset_frame_counter()
        self.recorder.start()

    def stop_recording(self) -> None:
        if self.mode != ModeState.RECORDING:
            return
        self.recorder.stop()

        self.replayer = ReplayerModel(
            self.recorder.get_file_list(),
            self.recorder.get_frame_rate(),
            self.frame_update_callback,
            self.display,
            self.FAST_MOVE_FRAME,
        )

        self.change_widget_state_for_recording(True)
        frame_num = self.replayer.capture.get_frame_num() - 1
        self.view.seekbar.config(from_=0, to=frame_num, state="enable")
        self.var_seekbar.set(frame_num)
        self.view.button_recording.configure(
            image=self.view.icon_record, command=self.start_recording, bootstyle="danger"
        )
        self.pause()

    def change_widget_state_for_recording(self, is_enabled: bool) -> None:
        state = "enable" if is_enabled else "disable"
        self.view.button_rewind.configure(state=state)
        self.view.button_prev.configure(state=state)
        self.view.button_play.configure(state=state)
        self.view.button_next.configure(state=state)
        self.view.button_forward.configure(state=state)
        self.view.button_set_point.configure(state=state)

    def play(self) -> None:
        if self.replayer is None:
            return
        self.mode = ModeState.PLAY
        self.view.button_play.configure(image=self.view.icon_pause, command=self.pause, bootstyle="warning")
        self.replayer.start_play(self._play_stop_callback)
        pass

    def pause(self) -> None:
        if self.replayer is None:
            return
        self.replayer.stop_play()

    def _play_stop_callback(self) -> None:
        self.mode = ModeState.PAUSE
        self.view.button_play.configure(image=self.view.icon_play, command=self.play, bootstyle="success")

    def press_rewind(self) -> None:
        # print("press_rewind")
        if self.replayer is None:
            return
        if self.mode == ModeState.PLAY:
            self.replayer.stop_play()
        self.replayer.rewind()

    def press_prev(self) -> None:
        # print("press_prev")
        if self.replayer is None:
            return
        if self.mode == ModeState.PLAY:
            self.replayer.stop_play()
        self.replayer.prev_frame()

    def press_next(self) -> None:
        # print("press_next")
        if self.replayer is None:
            return
        if self.mode == ModeState.PLAY:
            self.replayer.stop_play()
        self.replayer.next_frame()

    def press_forward(self) -> None:
        # print("press_forward")
        if self.replayer is None:
            return
        if self.mode == ModeState.PLAY:
            self.replayer.stop_play()
        self.replayer.fast_foward()

    def press_set_point(self) -> None:
        # print("Set point")
        if self.replayer is None:
            return
        now_frame = self.replayer.capture.get_now_frame()
        self.origin_point_frame_num = now_frame
        self.update_frame_counter_label(now_frame)

    def update_frame_counter_label(self, frame_num: int) -> None:
        if self.origin_point_frame_num is None:
            return
        if self.replayer is None:
            return
        diff_frame = frame_num - self.origin_point_frame_num

        if diff_frame >= 0:
            diff_time = self.replayer.frame_to_time(diff_frame)
            minute = diff_time // 60
            sec = diff_time % 60
        else:
            diff_time = self.replayer.frame_to_time(-diff_frame)
            minute = -(diff_time // 60)
            sec = diff_time % 60

        self.var_frame_counter.set(f"{minute:03.0f}:{sec:06.3f} ( {diff_frame:8d} frame )")

    def frame_update_callback(self, frame_num: int, frame_time: float) -> None:
        self.update_frame_counter_label(frame_num)
        self.var_seekbar.set(frame_num)
        self.update_seekbar_label(frame_time)

    def on_seekbar_change(self, event):  # NOQA
        frame_num = int(self.var_seekbar.get())
        if self.mode == ModeState.PLAY:
            self.replayer.stop_play()
        self.replayer.move_to(frame_num)
        self.update_frame_counter_label(frame_num)
        self.update_seekbar_label(self.replayer.frame_to_time(frame_num))

    def update_seekbar_label(self, frame_time: float) -> None:
        minute = frame_time // 60
        sec = frame_time % 60
        self.view.seekbar_right_label.configure(text=f"{minute:03.0f}:{sec:06.3f}")

    def reset_frame_counter(self) -> None:
        self.origin_point_frame_num = None
        self.var_frame_counter.set("FRAME COUNTER(from point)")

    def initialize_writer(
        self, file_list: List[str], user_settings: Model.UserSettings, writer_settings: Model.RingVideoWriterSetting
    ) -> None:
        self.recorder = RecorderModel(file_list, user_settings, writer_settings, self.display)


class Controller(object):
    def __init__(self, root: ttk.Window):
        self.root = root

        # 画面の定義
        self._controller_setting = _SettingController(root, self.setting_to_replayer)
        self._controller_replayer = _ReplayerController(root)

        self._error_label_input_device_error = ttk.Label(
            root,
            text="""
            設定した入力デバイスを開いています。
            30秒程度待ってもこの画面から切り替わらない場合はエラーです。

            ・他のソフトで指定した入力デバイスを使用していないか
            ・指定した解像度やフレームレートに対応しているか
            等を確認してください。
            一度画面を閉じてやりなおしてください。
            """,
        )

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._controller_setting.enable()

    def setting_to_replayer(self) -> None:
        self._controller_setting.disable()
        self._error_label_input_device_error.pack()
        self.root.attributes("-topmost", True)

        user_setting = self._controller_setting.get_settings()
        writer_setting = Model.RingVideoWriterSetting(FMT, FILE_LENGTH, WRITER_BUFFER_SIZE)

        file_num = int(user_setting.replay_time / FILE_LENGTH) + 1
        file_list = [f"{VIDEO_FOLDER_PATH}{VIDEO_NAME_PREFIX}{i}{VIDEO_NAME_EXTENSION}" for i in range(file_num)]

        # 動画保存用フォルダを空にする
        for file in file_list:
            # print(file)
            try:
                os.remove(file)
            except FileNotFoundError:
                pass

        self._controller_replayer.initialize_writer(file_list, user_setting, writer_setting)
        self._error_label_input_device_error.pack_forget()
        self._controller_replayer.enable()

    def on_close(self) -> None:
        if self._controller_replayer.replayer is not None:
            self._controller_replayer.replayer.release()
        if self._controller_replayer.recorder is not None:
            self._controller_replayer.recorder.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = ttk.Window(title="Quick Replay", themename="superhero", resizable=(False, False))

    controller = Controller(root)

    root.mainloop()

    cv2.destroyAllWindows()
