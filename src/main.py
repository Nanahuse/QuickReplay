"""Packaged Flet entry point for QuickReplay."""

import multiprocessing

from quickreplay.ui.app import run

if __name__ == "__main__":
    multiprocessing.freeze_support()
    run()
