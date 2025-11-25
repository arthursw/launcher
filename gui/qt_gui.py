"""Qt-based GUI implementation."""

import queue
from typing import TYPE_CHECKING

from gui.base_gui import BaseGUI

if TYPE_CHECKING:
    from launcher import Launcher

try:
    from PyQt5.QtWidgets import (
        QApplication,
        QMainWindow,
        QVBoxLayout,
        QWidget,
        QLabel,
        QProgressBar,
        QTextEdit,
        QDialog,
        QLineEdit,
        QPushButton,
    )
    from PyQt5.QtCore import QTimer, Qt
except ImportError:
    QMainWindow = None


class QtGUI(BaseGUI):
    """Qt-based GUI with progress bar and log display."""

    def __init__(self, launcher: "Launcher", event_queue: queue.Queue, response_queue: queue.Queue):
        """Initialize Qt GUI."""
        super().__init__(launcher, event_queue, response_queue)
        self.app = None
        self.window = None
        self.qt_available = QMainWindow is not None

    def show_proxy_dialog(self) -> dict:
        """Show proxy settings dialog using Qt.

        Returns:
            Dictionary with 'http' and 'https' proxy URLs
        """
        if not self.qt_available:
            return {"http": None, "https": None}

        dialog = QDialog(self.window)
        dialog.setWindowTitle("Proxy Configuration")
        dialog.setGeometry(100, 100, 400, 200)

        layout = QVBoxLayout()

        layout.addWidget(QLabel("HTTP Proxy URL:"))
        http_input = QLineEdit()
        layout.addWidget(http_input)

        layout.addWidget(QLabel("HTTPS Proxy URL:"))
        https_input = QLineEdit()
        layout.addWidget(https_input)

        result = {}

        def submit():
            result["http"] = http_input.text() or None
            result["https"] = https_input.text() or None
            dialog.accept()

        button = QPushButton("OK")
        button.clicked.connect(submit)
        layout.addWidget(button)

        dialog.setLayout(layout)
        dialog.exec_()

        return result

    def run(self) -> None:
        """Run Qt GUI."""
        if not self.qt_available:
            raise ImportError("PyQt5 is required for Qt GUI")

        self.app = QApplication([])
        self.window = QMainWindow()
        self.window.setWindowTitle("Application Launcher")
        self.window.setGeometry(100, 100, 600, 400)

        # Create central widget
        central_widget = QWidget()
        layout = QVBoxLayout()

        # Progress bar
        layout.addWidget(QLabel("Progress:"))
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # Log text
        layout.addWidget(QLabel("Logs:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        central_widget.setLayout(layout)
        self.window.setCentralWidget(central_widget)

        # Setup timer for event checking
        self.timer = QTimer()
        self.timer.timeout.connect(self._check_events)
        self.timer.start(100)

        self.window.show()
        self.app.exec_()

    def _check_events(self) -> None:
        """Check event queue for updates from worker thread."""
        try:
            event = self.event_queue.get_nowait()

            if event["type"] == "log":
                self.log_text.append(event["message"])

            elif event["type"] == "progress":
                current = event.get("current", 0)
                total = event.get("total", 100)
                percentage = int((current / total * 100) if total > 0 else 0)
                self.progress_bar.setValue(percentage)

            elif event["type"] == "error":
                self.log_text.append(f"ERROR: {event['message']}")

            elif event["type"] == "complete":
                self.timer.stop()
                self.window.close()

            elif event["type"] == "proxy_required":
                proxy_settings = self.show_proxy_dialog()
                self.response_queue.put(
                    {
                        "type": "proxy_settings",
                        "request_id": event.get("request_id"),
                        "data": proxy_settings,
                    }
                )

        except queue.Empty:
            pass
