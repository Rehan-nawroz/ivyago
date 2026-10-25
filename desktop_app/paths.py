"""Resource and data lookup for development and packaged desktop builds.

Bundled resources (the brand artwork) always ship inside the application
bundle. Model and database data, by contrast, live in the application root so
they can be downloaded, replaced, or removed without touching PyInstaller's
internal bundle directory. In repository mode the application root is the
project checkout; in a frozen build it is the folder that holds ``Ivyago.exe``.
"""

import sys
from pathlib import Path


_RESOURCE_NAMES = frozenset({"logo.png", "logo.ico", "ivyago-line.png"})
_RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIRECTORY_NAME = "model"


def desktop_resource_path(name: str) -> Path:
    """Return a known desktop resource path independent of the working dir."""

    if name not in _RESOURCE_NAMES:
        raise FileNotFoundError(f"Unknown desktop resource: {name}")

    path = _RESOURCE_ROOT / name
    if not path.is_file():
        raise FileNotFoundError(f"Desktop resource not found: {name}")
    return path


def resource_exists(name: str) -> bool:
    """Return whether a known desktop resource is available."""

    try:
        return desktop_resource_path(name).is_file()
    except FileNotFoundError:
        return False


def application_root() -> Path:
    """Return the folder that owns writable application data.

    A frozen Windows build keeps ``model/`` and ``db/`` beside the executable
    rather than inside ``_internal``, so the application remains self-contained
    while its larger assets stay inspectable and replaceable.
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def project_root() -> Path:
    """Return the repository/application root independent of the working dir."""

    return application_root()


def model_directory() -> Path:
    """Return the folder that holds local GGUF artifacts.

    The directory is not required to exist: callers verify the concrete file and
    turn a missing artifact into a typed provider error. Looking up a model path
    never touches the decorative resource table above.
    """

    return application_root() / MODEL_DIRECTORY_NAME


def model_file(name: str) -> Path:
    """Return the path of a named model artifact inside the model directory."""

    candidate = Path(name)
    if candidate.is_absolute() or candidate.name != name:
        raise ValueError(f"Model names must be bare file names: {name!r}")
    return model_directory() / name
