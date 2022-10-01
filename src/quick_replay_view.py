# Copyright (c) 2022 Nanahuse
# This software is released under the MIT License
# https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE


from typing import List
import ttkbootstrap as ttk
import ttkbootstrap.tooltip as ttk_tooltip


class _ViewBase(object):
    def enable(self) -> None:
        # 画面を有効にする
        pass

    def disable(self) -> None:
        # 画面を無効にする
        pass


class SettingView(ttk.Frame, _ViewBase):
    def __init__(self, parent):  # NOQA
        super().__init__(parent)
        self.parent = parent

        self.frame_setting = ttk.Frame(master=self)
        row = 0
        # webcam----------------------------------------------------------------------------------------
        self.webcam_label = ttk.Label(master=self.frame_setting, text="Web Camera", bootstyle="primary")
        self.webcam_label.grid(row=row, padx=5, pady=10)

        row += 1

        self.webcam_select_label = ttk.Label(master=self.frame_setting, text="入力デバイス")
        self.webcam_select_label.grid(row=row, column=0, padx=5, pady=5)
        self.webcam_select = ttk.Combobox(master=self.frame_setting, state="readonly")
        self.webcam_select.grid(row=row, column=1, padx=5, pady=5, sticky=ttk.W + ttk.E)

        row += 1

        self.webcam_resolution_label = ttk.Label(master=self.frame_setting, text="解像度")
        self.webcam_resolution_label.grid(row=row, column=0, padx=5, pady=5)
        self.webcam_resolution = ttk.Combobox(master=self.frame_setting, state="readonly")
        self.webcam_resolution.grid(row=row, column=1, padx=5, pady=5, sticky=ttk.W + ttk.E)

        row += 1

        self.webcam_framerate_label = ttk.Label(master=self.frame_setting, text="フレームレート [Hz]")
        self.webcam_framerate_label.grid(row=row, column=0, padx=5, pady=5)
        self.webcam_framerate = ttk.Spinbox(master=self.frame_setting, from_=1, to=120, state="readonly")
        self.webcam_framerate.grid(row=row, column=1, padx=5, pady=5, sticky=ttk.W + ttk.E)

        row += 1

        # replay----------------------------------------------------------------------------------------
        self.replay_label = ttk.Label(master=self.frame_setting, text="Replay", bootstyle="primary")
        self.replay_label.grid(row=row, padx=5, pady=10)

        row += 1

        self.replay_length_label = ttk.Label(master=self.frame_setting, text="リプレイ時間 [s]")
        self.replay_length_label.grid(row=row, column=0, padx=5, pady=5)
        self.replay_length = ttk.Spinbox(master=self.frame_setting, from_=10, to=86400, increment=10, state="readonly")
        self.replay_length.grid(row=row, column=1, padx=5, pady=5, sticky=ttk.W + ttk.E)

        # row += 1

        self.replay_auto_restart_label = ttk.Label(master=self.frame_setting, text="自動再開 [s]")
        # self.replay_auto_restart_label.grid(row=row, column=0, padx=5, pady=5)
        self.replay_auto_restart = ttk.Spinbox(
            master=self.frame_setting, from_=10, to=86400, increment=10, state="readonly"
        )
        # self.replay_auto_restart.grid(row=row, column=1, padx=5, pady=5, sticky=ttk.W + ttk.E)

        row += 1

        self.recording_preview_label = ttk.Label(master=self.frame_setting, text="録画時プレビュー")
        self.recording_preview_label.grid(row=row, padx=5, pady=10)

        self.recording_preview_frame = ttk.Frame(master=self.frame_setting)
        self.recording_preview_frame.grid(row=row, column=1, padx=5, pady=10, sticky=ttk.W + ttk.E)
        self.recording_preview_check_enable = ttk.Button(master=self.recording_preview_frame, text="Enable")
        self.recording_preview_check_enable.pack(side=ttk.LEFT, expand=True, fill=ttk.X)
        self.recording_preview_check_disable = ttk.Button(
            master=self.recording_preview_frame, text="disable", bootstyle="secondary"
        )
        self.recording_preview_check_disable.pack(side=ttk.RIGHT, expand=True, fill=ttk.X)

        row += 1

        self.frame_setting.columnconfigure(1, weight=1)
        self.frame_setting.pack(padx=5, pady=5, fill=ttk.X)

        # ---------------------------------------------------------------------------------------------------
        # ---------------------------------------------------------------------------------------------------

        row = 0

        self.frame_button = ttk.Frame(master=self)
        self.button_reset = ttk.Button(master=self.frame_button, text="Reset", bootstyle="warning", width=8)
        self.button_reset.grid(row=row, column=0, padx=15, pady=15)
        self.button_save = ttk.Button(master=self.frame_button, text="Save", bootstyle="success", width=8)
        self.button_save.grid(row=row, column=1, padx=15, pady=15)
        self.button_start = ttk.Button(master=self.frame_button, text="Start", bootstyle="default", width=8)
        self.button_start.grid(row=row, column=2, padx=15, pady=15)

        row += 1
        self.button_info = ttk.Button(master=self.frame_button, text="Info", width=8, bootstyle="secondary")
        self.button_info.grid(row=row, column=0, padx=15, pady=15)

        self.frame_button.pack(padx=5, pady=5, anchor=ttk.S)

    def enable(self) -> None:
        self.pack(padx=5, pady=5, fill=ttk.X)

    def disable(self) -> None:
        self.pack_forget()


class ReplayerView(ttk.Frame):
    CONTROL_BUTTON_CLEARANCE = 10

    def __init__(self, parent):  # NOQA
        super().__init__(parent)
        self.parent = parent

        # シークバー
        self.frame_seekbar = ttk.Frame(master=self)
        self.frame_seekbar.pack(padx=5, pady=15, fill=ttk.X)
        self.seekbar = ttk.Scale(master=self.frame_seekbar, bootstyle="default")
        self.seekbar.pack(padx=15, pady=5, side=ttk.LEFT, expand=True, fill=ttk.X)
        self.seekbar_right_label = ttk.Label(master=self.frame_seekbar, text="0:00/ -0:00")
        self.seekbar_right_label.pack(padx=5, side=ttk.RIGHT)

        self.icon_play = ttk.PhotoImage(file=r"./assets/play.png")
        self.icon_pause = ttk.PhotoImage(file=r"./assets/pause.png")
        self.icon_next = ttk.PhotoImage(file=r"./assets/next.png")
        self.icon_prev = ttk.PhotoImage(file=r"./assets/prev.png")
        self.icon_forward = ttk.PhotoImage(file=r"./assets/forward.png")
        self.icon_rewind = ttk.PhotoImage(file=r"./assets/rewind.png")
        self.icon_record = ttk.PhotoImage(file=r"./assets/record.png")
        self.icon_stop = ttk.PhotoImage(file=r"./assets/stop.png")

        # 再生用ボタン
        self.frame_video_button = ttk.Frame(master=self)
        self.frame_video_button.pack(padx=15, pady=10)
        self.button_rewind = ttk.Button(master=self.frame_video_button, image=self.icon_rewind, bootstyle="primary")
        self.button_rewind.pack(padx=self.CONTROL_BUTTON_CLEARANCE, pady=5, ipady=10, side=ttk.LEFT)
        self.button_prev = ttk.Button(master=self.frame_video_button, image=self.icon_prev, bootstyle="primary")
        self.button_prev.pack(padx=self.CONTROL_BUTTON_CLEARANCE, pady=5, ipady=10, side=ttk.LEFT, anchor=ttk.CENTER)
        self.button_play = ttk.Button(master=self.frame_video_button, image=self.icon_play, bootstyle="success")
        self.button_play.pack(padx=self.CONTROL_BUTTON_CLEARANCE, pady=5, ipady=10, side=ttk.LEFT)
        self.button_next = ttk.Button(master=self.frame_video_button, image=self.icon_next, bootstyle="primary")
        self.button_next.pack(padx=self.CONTROL_BUTTON_CLEARANCE, pady=5, ipady=10, side=ttk.LEFT)
        self.button_forward = ttk.Button(master=self.frame_video_button, image=self.icon_forward, bootstyle="primary")
        self.button_forward.pack(padx=self.CONTROL_BUTTON_CLEARANCE, pady=5, ipady=10, side=ttk.LEFT)

        separator = ttk.Separator(self.frame_video_button, orient="vertical")
        separator.pack(padx=10, pady=5, side=ttk.LEFT)

        self.button_recording = ttk.Button(master=self.frame_video_button, image=self.icon_record, bootstyle="danger")
        self.button_recording.pack(padx=self.CONTROL_BUTTON_CLEARANCE, pady=5, ipady=10, side=ttk.LEFT)

        # フレームカウンター
        self.frame_option_button = ttk.Frame(master=self)
        self.frame_option_button.pack(padx=5, pady=5, anchor=ttk.W, fill=ttk.X)
        self.button_set_point = ttk.Button(master=self.frame_option_button, text="Set point", bootstyle="secondary")
        self.button_set_point.pack(padx=20, pady=5, side=ttk.LEFT)
        self.counter_label = ttk.Label(master=self.frame_option_button, text="FRAME COUNTER(from point)")
        self.counter_label.pack(padx=20, pady=5, side=ttk.LEFT, fill=ttk.X)

        ttk_tooltip.ToolTip(self.button_rewind, text="早戻し")
        ttk_tooltip.ToolTip(self.button_prev, text="1コマ戻る")
        ttk_tooltip.ToolTip(self.button_play, text="再生")
        ttk_tooltip.ToolTip(self.button_next, text="1コマ進める")
        ttk_tooltip.ToolTip(self.button_forward, text="早送り")
        ttk_tooltip.ToolTip(self.button_set_point, text="タイマーの基点を設定")

    def enable(self) -> None:
        self.pack(padx=5, pady=5, fill=ttk.X)

    def disable(self) -> None:
        self.pack_forget()


class LicenseFrame(ttk.Frame):
    def __init__(self, parent):  # NOQA
        super().__init__(parent)
        self.parent = parent
        self.row = 0
        self.license_link_buttons: List[ttk.Button] = []

    def add(self, library_name: str, license_name: str) -> ttk.Button:
        self.name_label = ttk.Label(master=self, text=library_name)
        self.name_label.grid(row=self.row, column=0, padx=5, pady=5, sticky=ttk.W + ttk.E)
        self.license_link_buttons.append(ttk.Button(master=self, text=license_name, bootstyle="light-outline"))
        self.license_link_buttons[-1].grid(row=self.row, column=1, padx=10, pady=5, sticky=ttk.W + ttk.E)
        self.row += 1
        return self.license_link_buttons[-1]


class InfoView(ttk.Frame):
    def __init__(self, parent):  # NOQA
        super().__init__(parent)
        self.parent = parent
        self.info_label = ttk.Label(master=self, text="About this", bootstyle="success")
        self.info_label.pack(padx=10, pady=5, anchor=ttk.W)

        self.info_label = ttk.Label(master=self, text="Name\t: Quick Replay\nAuther\t: Nanahuse\nVersion\t: 1.0")
        self.info_label.pack(padx=10, pady=5, anchor=ttk.W)
        self.button_frame = ttk.Frame(master=self)
        self.button_frame.pack(anchor=ttk.W)
        self.github_link_button = ttk.Button(master=self.button_frame, text="Github", bootstyle="info-outline")
        self.github_link_button.pack(padx=10, pady=5, anchor=ttk.W, side=ttk.LEFT)
        self.license_link_button = ttk.Button(master=self.button_frame, text="MIT License", bootstyle="info-outline")
        self.license_link_button.pack(padx=10, pady=5, anchor=ttk.W, side=ttk.LEFT)

        self.thirdparty_label = ttk.Label(master=self, text="Third Party Licenses", bootstyle="success")
        self.thirdparty_label.pack(padx=10, pady=5, anchor=ttk.W)
        self.license_frame = LicenseFrame(self)
        self.license_frame.pack(padx=5, pady=5, fill=ttk.BOTH, anchor=ttk.W)

    def enable(self) -> None:
        self.pack(padx=5, pady=5, fill=ttk.BOTH)

    def disable(self) -> None:
        self.pack_forget()


if __name__ == "__main__":
    main_window = ttk.Window(themename="superhero", resizable=(False, False))
    main_window.title("Quick Replay")
    main_view = SettingView(main_window)
    main_view.enable()

    sub_window = ttk.Toplevel(main_window, resizable=(False, False))
    sub_window.title("Controller")
    sub_view = ReplayerView(sub_window)
    sub_view.enable()

    info_window = ttk.Toplevel(main_window, resizable=(False, False))
    info_window.title("Infomation")
    info = InfoView(info_window)

    import json

    with open("./assets/LICENSE_ThirdParty.json", encoding="UTF-8") as f:
        licenses = json.load(f)

    for tmp_license in licenses:
        info.license_frame.add(tmp_license["Name"], tmp_license["License"])

    info.enable()
    main_window.mainloop()
