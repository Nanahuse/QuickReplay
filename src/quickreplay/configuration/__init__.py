"""Version 2 configuration: versioned, validated JSON persistence.

The configuration layer maps a JSON file to typed immutable models and then to
the existing runtime settings.  It never performs application lifecycle, UI or
platform directory policy work.
"""

from quickreplay.configuration.codec import (
    config_from_json_object,
    config_to_json_object,
)
from quickreplay.configuration.errors import (
    ConfigurationError,
    ConfigurationParseError,
    ConfigurationReadError,
    ConfigurationValidationError,
    ConfigurationWriteError,
    UnsupportedConfigVersionError,
)
from quickreplay.configuration.models import (
    CURRENT_SCHEMA_VERSION,
    QuickReplayConfig,
    RecordingConfig,
    ReplayConfig,
    UiConfig,
)
from quickreplay.configuration.runtime import build_application_settings
from quickreplay.configuration.store import ConfigurationStore

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ConfigurationError",
    "ConfigurationParseError",
    "ConfigurationReadError",
    "ConfigurationStore",
    "ConfigurationValidationError",
    "ConfigurationWriteError",
    "QuickReplayConfig",
    "RecordingConfig",
    "ReplayConfig",
    "UiConfig",
    "UnsupportedConfigVersionError",
    "build_application_settings",
    "config_from_json_object",
    "config_to_json_object",
]
