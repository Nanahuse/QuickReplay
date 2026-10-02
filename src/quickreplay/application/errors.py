"""Errors raised by the application controller.

These are UI-independent; a future UI renders the application error events
instead of catching these exceptions directly.
"""


class ApplicationControllerError(RuntimeError):
    """Base class for application controller errors."""


class InvalidApplicationStateError(ApplicationControllerError):
    """An operation was requested in a state that does not allow it."""


class WorkerStartupError(ApplicationControllerError):
    """The recorder worker did not become ready."""


class WorkerExitedError(ApplicationControllerError):
    """The recorder worker exited unexpectedly."""


class ApplicationShutdownError(ApplicationControllerError):
    """The application could not be shut down cleanly."""
