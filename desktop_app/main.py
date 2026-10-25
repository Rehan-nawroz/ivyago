"""Process entry point for the Ivyago desktop application."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QDialog

from . import paths
from .app_state import AppState, create_initial_state
from .services.assistant_controller import AssistantController
from .services.assistant_service import (
    AssistantService,
    DefaultAssistantService,
)
from .services.chat_session_store import ChatSessionStore
from .services.conversation_controller import ConversationController
from .services.embedded_provider import EmbeddedProvider
from .services.model_provider import LocalModelProvider, RuntimeUnsupportedError
from .services.runtime_config import (
    ProviderKind,
    RuntimeConfig,
    default_runtime_config,
)
from .ui.main_window import MainWindow
from .ui.theme import build_app_stylesheet


def _apply_window_icon(app: QApplication) -> None:
    # The multi-resolution ICO is the canonical product icon: Windows picks the
    # exact 16/32/48/256 image instead of downscaling one large PNG.
    for name in ("logo.ico", "logo.png"):
        try:
            icon = QIcon(str(paths.desktop_resource_path(name)))
        except (FileNotFoundError, OSError):
            continue
        if not icon.isNull():
            app.setWindowIcon(icon)
            return


def _apply_palette(app: QApplication) -> None:
    """Keep native chrome such as tooltips consistent with the dark theme."""

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#08080C"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0E1015"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#12141A"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#0E1015"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#0E1015"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#FF1124"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)


def configure_tls_trust() -> None:
    """Anchor HTTPS verification to the bundled CA bundle.

    The one-time model download is the application's only TLS client. On
    Windows, Python trusts whichever certificate stores the host happens to
    expose, and a fresh machine (a new Windows install or a Windows Sandbox)
    can lack the root the model host chains to; the first request then fails
    with CERTIFICATE_VERIFY_FAILED. certifi ships inside the frozen bundle,
    so pointing SSL_CERT_FILE at it makes verification deterministic on every
    machine. An existing user or system override is never replaced.
    """

    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except ImportError:
        return
    bundle = certifi.where()
    if os.path.isfile(bundle):
        os.environ["SSL_CERT_FILE"] = bundle


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Create or reuse the Qt application and apply Ivyago metadata."""

    configure_tls_trust()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(sys.argv if argv is None else argv))

    metadata = create_initial_state().metadata
    app.setApplicationName(metadata.application_name)
    app.setApplicationDisplayName(metadata.application_name)
    app.setOrganizationName(metadata.organization_name)
    app.setApplicationVersion(metadata.version)
    app.setStyleSheet(build_app_stylesheet())
    _apply_palette(app)
    _apply_window_icon(app)
    return app


def build_provider(
    config: RuntimeConfig | None = None,
) -> LocalModelProvider:
    """Build the configured local provider; the default is always embedded."""

    resolved = config or default_runtime_config()
    if resolved.provider is ProviderKind.EMBEDDED:
        return EmbeddedProvider(resolved)

    # Explicit reference mode is not shipped in the packaged build and is never
    # selected as a fallback. Failing loudly is the honest behavior.
    raise RuntimeUnsupportedError(
        "The development Ollama provider is not included in this build."
    )


def build_assistant_service() -> AssistantService:
    """Compose the packaged offline assistant service.

    The service is built once per composition and injected into the controller;
    it never imports Qt, Ollama, or the legacy ``query_layer.answer()`` path.
    """

    return DefaultAssistantService()


def build_application_controller(
    config: RuntimeConfig | None = None,
) -> AssistantController:
    """Create the controller with the configured local provider and service."""

    return AssistantController(build_provider(config), build_assistant_service())


def build_chat_session_store() -> ChatSessionStore:
    """Return a fresh in-memory chat store (nothing is persisted)."""

    return ChatSessionStore()


def build_conversation_controller(
    config: RuntimeConfig | None = None,
) -> ConversationController:
    """Compose the in-memory conversation layer around the assistant controller.

    The provider, assistant service, and generation controller are built once
    here and injected into the UI; no widget constructs a model or a service.
    """

    return ConversationController(
        build_chat_session_store(),
        build_application_controller(config),
    )


def ensure_model_ready(spec=None) -> bool:
    """Return whether a complete local model is present, downloading it once.

    The downloader and its dialog are imported lazily so the assistant import
    graph (and every test that composes it) never pulls in an HTTP client.

    A missing model opens the modal setup dialog. Declining it returns
    ``False`` so the application exits without creating the main window.
    """

    configure_tls_trust()

    from .services.model_download import (
        default_model_download_spec,
        model_is_ready,
    )

    resolved = spec or default_model_download_spec()
    if model_is_ready(resolved):
        return True

    from .ui.model_setup_dialog import ModelSetupDialog

    dialog = ModelSetupDialog(resolved)
    return dialog.exec() == QDialog.DialogCode.Accepted


def create_main_window(
    state: AppState | None = None,
    controller: AssistantController | None = None,
    conversation_controller: ConversationController | None = None,
) -> MainWindow:
    """Create the shell window without starting the event loop."""

    return MainWindow(
        state or create_initial_state(), controller, conversation_controller
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Ivyago desktop event loop."""

    app = create_application(argv)
    if not ensure_model_ready():
        return 0
    conversation = build_conversation_controller()
    window = create_main_window(conversation_controller=conversation)
    window.show()
    conversation.assistant_controller().prepare()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
