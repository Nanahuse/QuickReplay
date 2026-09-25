"""Flet storage path resolution.

Durable configuration lives under ``FLET_APP_STORAGE_DATA``; regenerable runtime
data (segment buffer, replay assets) lives under ``FLET_APP_STORAGE_CACHE``.
The production resolver never falls back to the current working directory.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DATA_ENVIRONMENT_VARIABLE = "FLET_APP_STORAGE_DATA"
CACHE_ENVIRONMENT_VARIABLE = "FLET_APP_STORAGE_CACHE"


class StoragePathError(RuntimeError):
    """The Flet storage directories could not be resolved."""


@dataclass(frozen=True, slots=True)
class StoragePaths:
    """Resolved durable and cache directories."""

    data_directory: Path
    cache_directory: Path

    @property
    def config_path(self) -> Path:
        """Path of the durable ``config.json``."""
        return self.data_directory / "config.json"

    @property
    def runtime_directory(self) -> Path:
        """Working directory for the recorder buffer and replay assets."""
        return self.cache_directory / "runtime"


def resolve_storage_paths(*, data_directory: Path, cache_directory: Path) -> StoragePaths:
    """Build storage paths from explicit directories (used by tests and bootstrap)."""
    return StoragePaths(data_directory=Path(data_directory), cache_directory=Path(cache_directory))


def storage_paths_from_environment(
    environ: Mapping[str, str] | None = None,
) -> StoragePaths:
    """Resolve storage paths from the Flet storage environment variables."""
    source = os.environ if environ is None else environ
    data = source.get(DATA_ENVIRONMENT_VARIABLE)
    cache = source.get(CACHE_ENVIRONMENT_VARIABLE)
    if not data or not cache:
        raise StoragePathError(
            "could not resolve storage directories: "
            f"{DATA_ENVIRONMENT_VARIABLE} and {CACHE_ENVIRONMENT_VARIABLE} must be set"
        )
    return resolve_storage_paths(data_directory=Path(data), cache_directory=Path(cache))
