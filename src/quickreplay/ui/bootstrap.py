"""Desktop bootstrap: configuration, runtime settings and the application.

This module never imports Flet, so it can be exercised headlessly.
"""

from collections.abc import Callable
from dataclasses import dataclass

from quickreplay.application.controller import ApplicationController
from quickreplay.configuration.models import QuickReplayConfig
from quickreplay.configuration.runtime import build_application_settings
from quickreplay.configuration.store import ConfigurationStore
from quickreplay.ui.bridge import ApplicationUiBridge
from quickreplay.ui.paths import StoragePaths


@dataclass(frozen=True, slots=True)
class ApplicationBootstrap:
    """The assembled application objects for a desktop session."""

    paths: StoragePaths
    store: ConfigurationStore
    config: QuickReplayConfig
    controller: ApplicationController
    bridge: ApplicationUiBridge


def bootstrap_application(
    *,
    paths: StoragePaths,
    controller_factory: Callable[[object], ApplicationController] | None = None,
    bridge_factory: Callable[[ApplicationController], ApplicationUiBridge] | None = None,
) -> ApplicationBootstrap:
    """Load configuration and build the application controller and bridge.

    Configuration errors propagate to the caller so the UI can show a startup
    error instead of silently replacing a broken configuration with defaults.
    """
    store = ConfigurationStore(paths.config_path)
    config = store.load()
    settings = build_application_settings(config, working_directory=paths.runtime_directory)
    controller = (
        controller_factory(settings) if controller_factory else ApplicationController(settings)
    )
    bridge = bridge_factory(controller) if bridge_factory else ApplicationUiBridge(controller)
    return ApplicationBootstrap(
        paths=paths, store=store, config=config, controller=controller, bridge=bridge
    )
