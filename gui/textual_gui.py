"""Textual TUI implementation."""

import queue
from typing import TYPE_CHECKING

from gui.base_gui import BaseGUI

if TYPE_CHECKING:
    from launcher import Launcher

try:
    from textual.app import ComposeResult, App
    from textual.containers import Container
    from textual.widgets import Header, Footer, Static, ProgressBar, RichLog, Input, Button
    from textual.binding import Binding
except ImportError:
    App = None


class TextualGUI(BaseGUI):
    """Textual TUI with progress bar and log display."""

    def __init__(self, launcher: "Launcher", event_queue: queue.Queue, response_queue: queue.Queue):
        """Initialize Textual GUI."""
        super().__init__(launcher, event_queue, response_queue)
        self.textual_available = App is not None

    def show_proxy_dialog(self) -> dict:
        """Show proxy settings dialog in Textual TUI.

        Returns:
            Dictionary with 'http' and 'https' proxy URLs
        """
        result = {"http": None, "https": None}

        class ProxyDialog(App):
            def compose(self) -> ComposeResult:
                yield Header()
                yield Static("Proxy Configuration Required", classes="title")
                yield Static("HTTP Proxy URL:", classes="label")
                yield Input(id="http_proxy")
                yield Static("HTTPS Proxy URL:", classes="label")
                yield Input(id="https_proxy")
                yield Button("Submit", id="submit_btn", variant="primary")
                yield Footer()

            def on_button_pressed(self) -> None:
                http_input = self.query_one("#http_proxy", Input)
                https_input = self.query_one("#https_proxy", Input)
                result["http"] = http_input.value or None
                result["https"] = https_input.value or None
                self.exit()

        if self.textual_available:
            app = ProxyDialog()
            app.run()

        return result

    def run(self) -> None:
        """Run Textual GUI."""
        if not self.textual_available:
            raise ImportError("textual is required for Textual GUI")

        class LauncherApp(App):
            BINDINGS = [Binding("q", "quit", "Quit")]

            def __init__(self, parent_gui):
                super().__init__()
                self.parent_gui = parent_gui

            def compose(self) -> ComposeResult:
                yield Header()
                yield Static("Application Launcher", classes="title")
                yield Static("Progress:", classes="label")
                self.progress = ProgressBar(total=100)
                yield self.progress
                yield Static("Logs:", classes="label")
                self.log_widget = RichLog(markup=False)
                yield self.log_widget
                yield Footer()

            def on_mount(self) -> None:
                """Set up event checking."""
                self.set_interval(0.1, self._check_events)

            def _check_events(self) -> None:
                """Check event queue for updates."""
                try:
                    event = self.parent_gui.event_queue.get_nowait()

                    if event["type"] == "log":
                        self.log_widget.write(event["message"])

                    elif event["type"] == "progress":
                        current = event.get("current", 0)
                        total = event.get("total", 100)
                        if total > 0:
                            self.progress.update(progress=current)

                    elif event["type"] == "error":
                        self.log_widget.write(f"[bold red]ERROR:[/] {event['message']}")

                    elif event["type"] == "complete":
                        self.exit()

                    elif event["type"] == "proxy_required":
                        proxy_settings = self.parent_gui.show_proxy_dialog()
                        self.parent_gui.response_queue.put(
                            {
                                "type": "proxy_settings",
                                "request_id": event.get("request_id"),
                                "data": proxy_settings,
                            }
                        )

                except queue.Empty:
                    pass

        app = LauncherApp(self)
        app.run()
