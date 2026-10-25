"""Session-only state for the desktop foundation shell."""

from dataclasses import dataclass

from . import __version__
from .models import AppMetadata, NavigationDestination


@dataclass
class AppState:
    """Mutable presentation state that is intentionally not persisted."""

    selected_destination: NavigationDestination
    metadata: AppMetadata


def create_initial_state() -> AppState:
    """Return the default state for a new Ivyago desktop process."""

    return AppState(
        selected_destination=NavigationDestination.ASSIST,
        metadata=AppMetadata(
            application_name="Ivyago",
            organization_name="Ivyago",
            version=__version__,
        ),
    )
