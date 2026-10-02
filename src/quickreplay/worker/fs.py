"""Filesystem helpers for recording-session cleanup.

On Windows, deleting a directory immediately after ``os.replace`` can
transiently fail with a sharing violation or "directory not empty" even though
every writer has closed its file and the directory is already empty: the
platform can briefly report a stale directory entry for the replaced
temporary file.  :func:`remove_tree` performs a small, bounded retry for those
specific transient errors only; on other platforms it deletes once.
"""

import os
import shutil
import time
from pathlib import Path

_TRANSIENT_WINDOWS_ERRORS = frozenset({5, 32, 145})  # ACCESS_DENIED / SHARING / NOT_EMPTY
DEFAULT_ATTEMPTS = 6
DEFAULT_DELAY_SECONDS = 0.05


def remove_tree(
    path: Path,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
) -> None:
    """Remove a directory tree, retrying transient Windows delete failures.

    A missing path is treated as already removed.  Raises the last ``OSError``
    if the directory cannot be removed within the bounded attempt budget.
    """
    if not path.exists():
        return
    if os.name != "nt":
        shutil.rmtree(path)
        return

    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return  # a previous partial delete already removed it
        except OSError as exc:
            last_error = exc
            transient = getattr(exc, "winerror", None) in _TRANSIENT_WINDOWS_ERRORS
            if not transient or attempt + 1 >= attempts or not path.exists():
                raise
            time.sleep(delay_seconds * (attempt + 1))
    if last_error is not None:  # pragma: no cover - defensive
        raise last_error
