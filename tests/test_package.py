"""Smoke test for the QuickReplay Version 2 package skeleton."""

import quickreplay


def test_package_import() -> None:
    assert quickreplay.__version__ == "2.0.0.dev0"
