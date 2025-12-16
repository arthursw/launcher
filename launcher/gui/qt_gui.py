"""Qt (PySide6) GUI implementation for the launcher."""

import queue
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTextEdit,
    QPushButton,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QFormLayout,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from .base import BaseGUI
from ..worker import WorkerEvent, GUIResponse


class ProxyDialog(QDialog):
    """Dialog for entering proxy settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Proxy Settings")
        self.setModal(True)
        self.setMinimumWidth(400)

        self.http_proxy: Optional[str] = None
        self.https_proxy: Optional[str] = None

        layout = QVBoxLayout(self)

        # Form
        form_layout = QFormLayout()

        self.http_edit = QLineEdit()
        self.http_edit.setPlaceholderText("http://username:password@proxy.example.com:8080")
        form_layout.addRow("HTTP Proxy:", self.http_edit)

        self.https_edit = QLineEdit()
        self.https_edit.setPlaceholderText("https://username:password@proxy.example.com:8080")
        form_layout.addRow("HTTPS Proxy:", self.https_edit)

        layout.addLayout(form_layout)

        # Hint
        hint = QLabel("Format: http://username:password@proxy.example.com:8080")
        hint.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(hint)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        self.http_proxy = self.http_edit.text().strip() or None
        self.https_proxy = self.https_edit.text().strip() or None
        super().accept()


class InitTimeoutDialog(QDialog):
    """Dialog for init timeout action."""

    def __init__(self, message: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Initialization Timeout")
        self.setModal(True)
        self.setMinimumWidth(400)

        self.action = "exit"

        layout = QVBoxLayout(self)

        # Message
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)

        question = QLabel("What would you like to do?")
        layout.addWidget(question)

        # Buttons
        button_layout = QHBoxLayout()

        wait_btn = QPushButton("Wait More")
        wait_btn.clicked.connect(self._wait)
        button_layout.addWidget(wait_btn)

        reinstall_btn = QPushButton("Reinstall")
        reinstall_btn.clicked.connect(self._reinstall)
        button_layout.addWidget(reinstall_btn)

        exit_btn = QPushButton("Exit")
        exit_btn.clicked.connect(self._exit)
        button_layout.addWidget(exit_btn)

        layout.addLayout(button_layout)

    def _wait(self):
        self.action = "wait"
        self.accept()

    def _reinstall(self):
        self.action = "reinstall"
        self.accept()

    def _exit(self):
        self.action = "exit"
        self.reject()


class QtGUI(BaseGUI):
    """Qt (PySide6) GUI for the launcher."""

    def __init__(
        self,
        event_queue: queue.Queue[WorkerEvent],
        response_queue: queue.Queue[GUIResponse],
        app_name: str = "Launcher",
    ) -> None:
        super().__init__(event_queue, response_queue, app_name)
        self._app: Optional[QApplication] = None
        self._window: Optional[QMainWindow] = None
        self._progress_bar: Optional[QProgressBar] = None
        self._progress_label: Optional[QLabel] = None
        self._log_text: Optional[QTextEdit] = None
        self._close_button: Optional[QPushButton] = None
        self._timer: Optional[QTimer] = None

    def _create_window(self) -> None:
        """Create the main window."""
        # Create application if needed
        if QApplication.instance() is None:
            self._app = QApplication([])
        else:
            self._app = QApplication.instance()

        # Main window
        self._window = QMainWindow()
        self._window.setWindowTitle(f"{self.app_name} - Launcher")
        self._window.setMinimumSize(600, 400)

        # Central widget
        central = QWidget()
        self._window.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Progress section
        self._progress_label = QLabel("Starting...")
        layout.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # Indeterminate
        layout.addWidget(self._progress_bar)

        # Log section
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Courier", 10))
        layout.addWidget(self._log_text, stretch=1)

        # Button section
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self._close_button = QPushButton("Close")
        self._close_button.setEnabled(False)
        self._close_button.clicked.connect(self._on_close)
        button_layout.addWidget(self._close_button)

        layout.addLayout(button_layout)

        # Timer for checking events
        self._timer = QTimer()
        self._timer.timeout.connect(self._check_events)
        self._timer.start(100)

    def _update_progress(self, current: int, total: int, message: str) -> None:
        """Update progress bar and label."""
        if self._progress_label:
            self._progress_label.setText(message)

        if self._progress_bar:
            if total > 0:
                self._progress_bar.setRange(0, total)
                self._progress_bar.setValue(current)
            else:
                self._progress_bar.setRange(0, 0)  # Indeterminate

    def _append_log(self, message: str) -> None:
        """Append message to log."""
        if self._log_text:
            self._log_text.append(message)

    def _show_proxy_dialog(self, request_id: str) -> None:
        """Show proxy settings dialog."""
        if not self._window:
            return

        dialog = ProxyDialog(self._window)
        if dialog.exec() == QDialog.Accepted:
            self._submit_proxy_response(request_id, dialog.http_proxy, dialog.https_proxy)
        else:
            self._submit_proxy_response(request_id, None, None)

    def _show_init_timeout_dialog(self, request_id: str, message: str) -> None:
        """Show init timeout dialog."""
        if not self._window:
            return

        dialog = InitTimeoutDialog(message, self._window)
        dialog.exec()
        self._submit_init_timeout_response(request_id, dialog.action)

    def _show_error(self, message: str) -> None:
        """Show error message."""
        if self._progress_bar:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(0)

        if self._progress_label:
            self._progress_label.setText("Error occurred")

        if self._close_button:
            self._close_button.setEnabled(True)

        self._append_log(f"ERROR: {message}")

        if self._window:
            QMessageBox.critical(self._window, "Error", message)

    def _show_complete(self) -> None:
        """Handle completion."""
        if self._progress_bar:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(100)

        if self._progress_label:
            self._progress_label.setText("Complete!")

        if self._close_button:
            self._close_button.setEnabled(True)

        self._append_log("Launcher complete. Application is running.")

    def _process_events_once(self) -> bool:
        """Process Qt events."""
        if not self._app:
            return False

        self._app.processEvents()
        return self._window is not None and self._window.isVisible()

    def _on_close(self) -> None:
        """Handle window close."""
        if self._timer:
            self._timer.stop()
        if self._window:
            self._window.close()
            self._window = None

    def show(self) -> None:
        """Show the window."""
        if self._window:
            self._window.show()

    def hide(self) -> None:
        """Hide the window."""
        if self._window:
            self._window.hide()

    def destroy(self) -> None:
        """Destroy the GUI."""
        if self._timer:
            self._timer.stop()
        if self._window:
            self._window.close()
            self._window = None
