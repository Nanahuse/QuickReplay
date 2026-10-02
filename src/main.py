"""Packaged Flet entry point for QuickReplay."""

import multiprocessing
import sys

from quickreplay.ui.about_window import run_about_from_command_line
from quickreplay.ui.app import run

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--quickreplay-about"]:
        run_about_from_command_line()
    else:
        run()
