"""First-run model setup dialog.

Ivyago cannot answer without its local model file, so this modal dialog owns the
one-time download before the main window appears. It is presentation only: all
network work happens in :class:`~desktop_app.services.model_download.ModelDownloader`
on a background thread, and the dialog can be tested with a fake downloader
without touching a network.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..services.model_download import (
    MESSAGE_NETWORK,
    STATE_CANCELLED,
    STATE_DONE,
    STATE_DOWNLOADING,
    STATE_FAILED,
    STATE_IDLE,
    STATE_VERIFYING,
    ModelDownloader,
    ModelDownloadSpec,
    default_model_download_spec,
)
from . import assets

_DOWNLOAD_CAPTION = "One-time download"


def format_size(byte_count: int) -> str:
    """Return a compact decimal size for user-facing copy."""

    if byte_count >= 1_000_000_000:
        return f"{byte_count / 1_000_000_000:.1f} GB"
    if byte_count >= 1_000_000:
        return f"{byte_count / 1_000_000:.0f} MB"
    return f"{max(1, round(byte_count / 1_000))} KB"


class ModelSetupDialog(QDialog):
    """Modal first-run download with explicit progress and recovery states."""

    def __init__(
        self,
        spec: ModelDownloadSpec | None = None,
        downloader: ModelDownloader | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.spec = spec or default_model_download_spec()
        self._downloader = downloader or ModelDownloader(self.spec, self)
        self._state = STATE_IDLE
        self.destination: str | None = None

        self.setObjectName("modelSetupDialog")
        self.setWindowTitle("Set up Ivyago")
        self.setModal(True)
        self.setMinimumWidth(580)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setAccessibleName("Set up Ivyago")

        self._build()
        self._connect()
        self._set_state(STATE_IDLE)

    # -- construction -----------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 26, 28, 24)
        outer.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)

        self.brand_mark = QLabel(self)
        self.brand_mark.setObjectName("setupBrandMark")
        self.brand_mark.setFixedSize(48, 48)
        self.brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_mark.setAccessibleName("Ivyago nurse mark")
        try:
            self.brand_mark.setPixmap(assets.brand_mark(44))
        except (FileNotFoundError, OSError):
            self.brand_mark.setText("I")
            self.brand_mark.setObjectName("brandMarkFallback")

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)

        self.title_label = QLabel("Set up the offline assistant", self)
        self.title_label.setObjectName("setupTitle")
        self.title_label.setWordWrap(True)

        self.caption_label = QLabel(_DOWNLOAD_CAPTION, self)
        self.caption_label.setObjectName("setupDetail")

        titles.addWidget(self.title_label)
        titles.addWidget(self.caption_label)
        titles.addStretch(1)

        header.addWidget(self.brand_mark, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(titles, 1)
        outer.addLayout(header)

        self.body_label = QLabel(
            "Ivyago needs its language model ("
            f"{format_size(self.spec.expected_size)}"
            ") before it can answer. The download happens once; after that "
            "Ivyago works without an internet connection.",
            self,
        )
        self.body_label.setObjectName("setupBody")
        self.body_label.setWordWrap(True)
        outer.addWidget(self.body_label)

        self.privacy_label = QLabel(
            "Only the model file is requested from its official source. "
            "Messages, prompts, and personal details are never sent.",
            self,
        )
        self.privacy_label.setObjectName("setupDetail")
        self.privacy_label.setWordWrap(True)
        outer.addWidget(self.privacy_label)

        rule = QFrame(self)
        rule.setObjectName("setupRule")
        rule.setFixedHeight(1)
        outer.addWidget(rule)

        self.progress = QProgressBar(self)
        self.progress.setObjectName("setupProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Model download progress")
        outer.addWidget(self.progress)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("setupStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Download status")
        outer.addWidget(self.status_label)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("setupError")
        self.error_label.setWordWrap(True)
        self.error_label.setAccessibleName("Download error")
        outer.addWidget(self.error_label)

        # Secondary line with the concrete transport failure (timeout, DNS,
        # certificate, HTTP status). It is shown only for network failures,
        # where the reason never contains local paths or model details, so a
        # blocked or misbehaving network becomes diagnosable instead of
        # collapsing into one generic message.
        self.technical_label = QLabel("", self)
        self.technical_label.setObjectName("setupDetail")
        self.technical_label.setWordWrap(True)
        self.technical_label.setAccessibleName("Download technical detail")
        self.technical_label.setVisible(False)
        outer.addWidget(self.technical_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)

        self.secondary_button = QPushButton("Quit", self)
        self.secondary_button.setObjectName("secondaryButton")
        self.secondary_button.setAutoDefault(False)
        self.secondary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.secondary_button.clicked.connect(self._secondary_clicked)
        buttons.addWidget(self.secondary_button)

        self.primary_button = QPushButton("Download model", self)
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setAutoDefault(True)
        self.primary_button.setDefault(True)
        self.primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.primary_button.clicked.connect(self._primary_clicked)
        buttons.addWidget(self.primary_button)

        outer.addLayout(buttons)

    def _connect(self) -> None:
        self._downloader.progress.connect(self._on_progress)
        self._downloader.state_changed.connect(self._on_state)
        self._downloader.failed.connect(self._on_failed)
        self._downloader.finished.connect(self._on_finished)

    # -- states -----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._state = state
        running = state in (STATE_DOWNLOADING, STATE_VERIFYING)

        if state == STATE_DOWNLOADING:
            self.primary_button.setText("Downloading\u2026")
            self.primary_button.setAccessibleName("Downloading the assistant model")
            self.primary_button.setEnabled(False)
            self.secondary_button.setText("Cancel download")
            self.secondary_button.setAccessibleName("Cancel model download")
            self.secondary_button.setEnabled(True)
            self.progress.setVisible(True)
            self.status_label.setVisible(True)
            self.error_label.setVisible(False)
            self.progress.setValue(0)
            self.status_label.setText(
                f"Downloading\u2026 0% of {format_size(self.spec.expected_size)}"
            )
        elif state == STATE_VERIFYING:
            self.primary_button.setText("Verifying\u2026")
            self.primary_button.setAccessibleName("Verifying the assistant model")
            self.primary_button.setEnabled(False)
            self.secondary_button.setText("Cancel")
            self.secondary_button.setAccessibleName("Cancel model verification")
            self.secondary_button.setEnabled(False)
            self.progress.setVisible(True)
            self.status_label.setVisible(True)
            self.error_label.setVisible(False)
            self.status_label.setText("Verifying the downloaded file\u2026")
        elif state == STATE_CANCELLED:
            self.primary_button.setText("Resume download")
            self.primary_button.setAccessibleName("Resume the assistant model download")
            self.primary_button.setEnabled(True)
            self.secondary_button.setText("Quit")
            self.secondary_button.setAccessibleName("Quit Ivyago")
            self.secondary_button.setEnabled(True)
            self.progress.setVisible(False)
            self.status_label.setVisible(True)
            self.error_label.setVisible(False)
            self.status_label.setText(
                "Download paused. You can resume from where it stopped."
            )
        elif state == STATE_FAILED:
            self.primary_button.setText("Retry")
            self.primary_button.setAccessibleName("Retry the model download")
            self.primary_button.setEnabled(True)
            self.secondary_button.setText("Quit")
            self.secondary_button.setAccessibleName("Quit Ivyago")
            self.secondary_button.setEnabled(True)
            self.progress.setVisible(False)
            self.status_label.setVisible(False)
            self.error_label.setVisible(True)
            self.technical_label.setVisible(bool(self.technical_label.text()))
        elif state == STATE_DONE:
            self.accept()
        else:  # STATE_IDLE
            self.primary_button.setText("Download model")
            self.primary_button.setAccessibleName("Download the assistant model")
            self.primary_button.setEnabled(True)
            self.secondary_button.setText("Quit")
            self.secondary_button.setAccessibleName("Quit Ivyago")
            self.secondary_button.setEnabled(True)
            self.progress.setVisible(False)
            self.status_label.setVisible(False)
            self.error_label.setVisible(False)

        if state != STATE_FAILED:
            self.technical_label.setVisible(False)

        self.primary_button.setDefault(not running)
        self.primary_button.setAutoDefault(not running)
        if not running:
            self.primary_button.setFocus()

    # -- downloader signals ------------------------------------------------

    def _on_progress(self, received: int, total: int) -> None:
        if total <= 0:
            return
        percent = max(0, min(100, round(received * 100 / total)))
        self.progress.setValue(percent)
        self.progress.setAccessibleDescription(f"{percent} percent downloaded")
        if self._state == STATE_VERIFYING:
            self.status_label.setText("Verifying the downloaded file\u2026")
            return
        self.status_label.setText(
            f"Downloading\u2026 {percent}% of {format_size(total)}"
        )

    def _on_state(self, state: str) -> None:
        if state in (STATE_CANCELLED, STATE_VERIFYING):
            self._set_state(state)

    def _on_failed(self, message: str) -> None:
        self.error_label.setText(message)
        self.technical_label.setText(self._technical_detail(message))
        self._set_state(STATE_FAILED)
        self.error_label.setVisible(True)

    def _technical_detail(self, message: str) -> str:
        """Return the underlying failure reason for network errors only.

        The downloader records the transport exception in ``last_error``; the
        UI otherwise collapses every connectivity problem into one friendly
        sentence. Network errors never carry local file paths or model
        details, while write/checksum errors can, so only the network message
        is eligible for this second line.
        """

        if message != MESSAGE_NETWORK:
            return ""
        raw = getattr(self._downloader, "last_error", None)
        if not raw:
            return ""
        detail = " ".join(str(raw).split())
        if len(detail) > 240:
            detail = detail[:237] + "..."
        return f"Technical detail: {detail}"

    def _on_finished(self, path: str) -> None:
        self.destination = path
        self._set_state(STATE_DONE)

    # -- buttons ----------------------------------------------------------

    def _primary_clicked(self) -> None:
        if self._state in (STATE_IDLE, STATE_CANCELLED, STATE_FAILED):
            self._start_download()

    def _secondary_clicked(self) -> None:
        if self._state == STATE_DOWNLOADING:
            self.secondary_button.setEnabled(False)
            self._downloader.cancel()
            return
        self.reject()

    def _start_download(self) -> None:
        self.error_label.setText("")
        self.technical_label.setText("")
        self._set_state(STATE_DOWNLOADING)
        self._downloader.start()

    # -- lifecycle --------------------------------------------------------

    def done(self, result: int) -> None:
        self._shutdown_downloader()
        super().done(result)

    def reject(self) -> None:
        if self._state in (STATE_DOWNLOADING, STATE_VERIFYING):
            self._downloader.cancel()
        super().reject()

    def _shutdown_downloader(self) -> None:
        shutdown = getattr(self._downloader, "shutdown", None)
        if callable(shutdown):
            shutdown()
