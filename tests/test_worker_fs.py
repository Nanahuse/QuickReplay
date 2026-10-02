"""Bounded, transient-only retry for recording-session directory cleanup."""

import types
from pathlib import Path

import pytest

from quickreplay.worker import fs


class _TransientOSError(OSError):
    def __init__(self, winerror: int) -> None:
        super().__init__("transient filesystem error")
        self.winerror = winerror


def _windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(fs.time, "sleep", lambda _seconds: None)


def test_missing_path_is_a_noop() -> None:
    fs.remove_tree(Path("does-not-exist-12345"))


def test_retries_transient_windows_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def fake_rmtree(path: Path, **kwargs) -> None:
        calls["count"] += 1
        if calls["count"] < 3:
            raise _TransientOSError(32)

    monkeypatch.setattr(fs.shutil, "rmtree", fake_rmtree)
    _windows(monkeypatch)

    fs.remove_tree(tmp_path)

    assert calls["count"] == 3


def test_gives_up_after_bounded_attempts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def fake_rmtree(path: Path, **kwargs) -> None:
        calls["count"] += 1
        raise _TransientOSError(145)

    monkeypatch.setattr(fs.shutil, "rmtree", fake_rmtree)
    _windows(monkeypatch)

    with pytest.raises(OSError):
        fs.remove_tree(tmp_path, attempts=2)
    assert calls["count"] == 2


def test_non_transient_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"count": 0}

    def fake_rmtree(path: Path, **kwargs) -> None:
        calls["count"] += 1
        raise _TransientOSError(1)

    monkeypatch.setattr(fs.shutil, "rmtree", fake_rmtree)
    _windows(monkeypatch)

    with pytest.raises(OSError):
        fs.remove_tree(tmp_path)
    assert calls["count"] == 1


def test_non_windows_deletes_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def fake_rmtree(path: Path, **kwargs) -> None:
        calls["count"] += 1

    monkeypatch.setattr(fs.shutil, "rmtree", fake_rmtree)
    monkeypatch.setattr(fs, "os", types.SimpleNamespace(name="posix"))

    fs.remove_tree(tmp_path)

    assert calls["count"] == 1
