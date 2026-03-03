"""Textual TUI implementation for the launcher."""

import queue
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Input, Label, ProgressBar, RichLog, Static
from textual.screen import ModalScreen

from .base import BaseGUI
from ..worker import WorkerEvent, GUIResponse


class ProxyScreen(ModalScreen[tuple[Optional[str], Optional[str], Optional[str]]]):
    """Modal screen for proxy settings."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(id="proxy-dialog"):
            yield Label("Proxy Settings", id="proxy-title")
            yield Label("HTTP Proxy:")
            yield Input(placeholder="http://user:pass@proxy:8080", id="http-proxy")
            yield Label("HTTPS Proxy:")
            yield Input(placeholder="https://user:pass@proxy:8080", id="https-proxy")
            yield Label("SSL Certificate (optional):")
            yield Input(placeholder="/path/to/certificate.pem", id="ssl-cert")
            with Horizontal(id="proxy-buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            http = self.query_one("#http-proxy", Input).value.strip() or None
            https = self.query_one("#https-proxy", Input).value.strip() or None
            ssl_cert = self.query_one("#ssl-cert", Input).value.strip() or None
            self.dismiss((http, https, ssl_cert))
        else:
            self.dismiss((None, None, None))

    def action_cancel(self) -> None:
        self.dismiss((None, None, None))


class InitTimeoutScreen(ModalScreen[str]):
    """Modal screen for init timeout action."""

    BINDINGS = [("escape", "exit", "Exit")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Container(id="timeout-dialog"):
            yield Label("Initialization Timeout", id="timeout-title")
            yield Label(self.message, id="timeout-message")
            yield Label("What would you like to do?")
            with Horizontal(id="timeout-buttons"):
                yield Button("Wait More", id="wait")
                yield Button("Reinstall", variant="warning", id="reinstall")
                yield Button("Exit", variant="error", id="exit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_exit(self) -> None:
        self.dismiss("exit")


class LauncherApp(App):
    """Textual application for the launcher."""

    CSS = """
    #main-container {
        padding: 1;
    }

    #progress-container {
        height: 3;
        margin-bottom: 1;
    }

    #progress-label {
        width: 100%;
    }

    #log-container {
        height: 1fr;
        border: solid green;
    }

    #button-container {
        height: 3;
        align: right middle;
    }

    #proxy-dialog, #timeout-dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    #proxy-title, #timeout-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #proxy-buttons, #timeout-buttons {
        margin-top: 1;
        align: center middle;
    }

    #proxy-buttons Button, #timeout-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(
        self,
        event_queue: queue.Queue[WorkerEvent],
        response_queue: queue.Queue[GUIResponse],
        app_name: str = "Launcher",
    ):
        super().__init__()
        self.event_queue = event_queue
        self.response_queue = response_queue
        self.app_name = app_name
        self._completed = False
        self._current_request_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Container(id="main-container"):
            yield Label(f"{self.app_name} - Launcher", id="app-title")
            with Container(id="progress-container"):
                yield Label("Starting...", id="progress-label")
                yield ProgressBar(id="progress-bar", show_eta=False)
            yield RichLog(id="log", highlight=True, markup=True)
            with Horizontal(id="button-container"):
                yield Button("Close", id="close", disabled=True)

    def on_mount(self) -> None:
        """Called when app is mounted."""
        self.set_interval(0.1, self._check_events)

    def _check_events(self) -> None:
        """Check for events from worker."""
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass

    def _handle_event(self, event: WorkerEvent) -> None:
        """Handle a worker event."""
        from ..worker import EventType

        if event.type == EventType.LOG:
            self.query_one("#log", RichLog).write(event.message)
        elif event.type == EventType.PROGRESS:
            self.query_one("#progress-label", Label).update(event.message)
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            if event.total > 0:
                progress_bar.update(total=event.total, progress=event.current)
            else:
                progress_bar.update(total=100, progress=None)  # Indeterminate
        elif event.type == EventType.PROXY_REQUIRED:
            self._current_request_id = event.request_id
            self.push_screen(ProxyScreen(), self._on_proxy_result)
        elif event.type == EventType.INIT_TIMEOUT:
            self._current_request_id = event.request_id
            self.push_screen(InitTimeoutScreen(event.message), self._on_timeout_result)
        elif event.type == EventType.ERROR:
            self.query_one("#progress-label", Label).update("Error occurred")
            self.query_one("#log", RichLog).write(f"[red]ERROR: {event.message}[/red]")
            self.query_one("#close", Button).disabled = False
        elif event.type == EventType.COMPLETE:
            self._completed = True
            self.query_one("#progress-label", Label).update("Complete!")
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.update(total=100, progress=100)
            self.query_one("#log", RichLog).write("[green]Launcher complete. Application is running.[/green]")
            self.query_one("#close", Button).disabled = False

    def _on_proxy_result(self, result: tuple[Optional[str], Optional[str], Optional[str]]) -> None:
        """Handle proxy dialog result."""
        from ..worker import GUIResponse, ResponseType

        http, https, ssl_cert = result
        response = GUIResponse(
            type=ResponseType.PROXY_SETTINGS,
            request_id=self._current_request_id or "",
            data={"http": http, "https": https, "ssl_cert_file": ssl_cert},
        )
        self.response_queue.put(response)

    def _on_timeout_result(self, action: str) -> None:
        """Handle timeout dialog result."""
        from ..worker import GUIResponse, ResponseType

        response = GUIResponse(
            type=ResponseType.INIT_TIMEOUT_RESPONSE,
            request_id=self._current_request_id or "",
            data={"action": action},
        )
        self.response_queue.put(response)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "close":
            self.exit()


class TextualGUI(BaseGUI):
    """Textual TUI for the launcher.

    Note: This GUI works differently from Tkinter/Qt.
    The Textual app runs its own event loop, so run() will block
    until the app exits.
    """

    def __init__(
        self,
        event_queue: queue.Queue[WorkerEvent],
        response_queue: queue.Queue[GUIResponse],
        app_name: str = "Launcher",
    ) -> None:
        super().__init__(event_queue, response_queue, app_name)
        self._app: Optional[LauncherApp] = None

    def _create_window(self) -> None:
        """Create the Textual app."""
        self._app = LauncherApp(
            self.event_queue,
            self.response_queue,
            self.app_name,
        )

    def _update_progress(self, current: int, total: int, message: str) -> None:
        """Not used - handled internally by LauncherApp."""
        pass

    def _append_log(self, message: str) -> None:
        """Not used - handled internally by LauncherApp."""
        pass

    def _show_proxy_dialog(self, request_id: str) -> None:
        """Not used - handled internally by LauncherApp."""
        pass

    def _show_init_timeout_dialog(self, request_id: str, message: str) -> None:
        """Not used - handled internally by LauncherApp."""
        pass

    def _show_error(self, message: str) -> None:
        """Not used - handled internally by LauncherApp."""
        pass

    def _show_complete(self) -> None:
        """Not used - handled internally by LauncherApp."""
        pass

    def _process_events_once(self) -> bool:
        """Not used - Textual has its own event loop."""
        return False

    def show(self) -> None:
        """Not applicable for Textual."""
        pass

    def hide(self) -> None:
        """Not applicable for Textual."""
        pass

    def destroy(self) -> None:
        """Exit the Textual app."""
        if self._app:
            self._app.exit()
            self._app = None

    def run(self) -> None:
        """Run the Textual app.

        This blocks until the app exits.
        """
        if not self._app:
            self._create_window()

        if self._app:
            self._app.run()
            self._completed = self._app._completed
