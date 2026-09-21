"""File persistence for the configuration.

The store knows only about JSON files and the configuration codec; it never
imports the application controller, the recorder worker or the replay
controller.  Saves are atomic: the new file is written to a temporary sibling,
flushed, fsynced, closed and then ``os.replace``d over the destination.
"""

import json
import os
from pathlib import Path

from quickreplay.configuration.codec import (
    config_from_json_object,
    config_to_json_object,
)
from quickreplay.configuration.errors import (
    ConfigurationParseError,
    ConfigurationReadError,
    ConfigurationWriteError,
)
from quickreplay.configuration.models import QuickReplayConfig


class ConfigurationStore:
    """Load and save a :class:`QuickReplayConfig` at a fixed path."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> QuickReplayConfig:
        """Return the stored configuration, or defaults when the file is absent."""
        if not self._path.exists():
            return QuickReplayConfig()
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationReadError(
                f"could not read the configuration file {self._path}: {exc}"
            ) from exc
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigurationParseError(
                f"the configuration file {self._path} is not valid JSON: {exc}"
            ) from exc
        return config_from_json_object(value)

    def save(self, config: QuickReplayConfig) -> None:
        """Write *config* atomically as canonical UTF-8 JSON."""
        payload = json.dumps(config_to_json_object(config), indent=2, ensure_ascii=False) + "\n"
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._path)
        except OSError as exc:
            _remove_quietly(tmp_path)
            raise ConfigurationWriteError(
                f"could not write the configuration file {self._path}: {exc}"
            ) from exc


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
