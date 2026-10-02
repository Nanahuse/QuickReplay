"""Errors raised by the configuration component."""


class ConfigurationError(RuntimeError):
    """Base class for configuration errors."""


class ConfigurationReadError(ConfigurationError):
    """Reading the configuration file failed."""


class ConfigurationParseError(ConfigurationError):
    """The configuration file is not valid JSON."""


class ConfigurationValidationError(ConfigurationError):
    """The configuration does not match the schema."""


class UnsupportedConfigVersionError(ConfigurationError):
    """The configuration schema version is not supported."""


class ConfigurationWriteError(ConfigurationError):
    """Writing the configuration file failed."""
