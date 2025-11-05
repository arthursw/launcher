import asyncio
from textual.app import App, ComposeResult, RenderResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Log, Input, Button, Static, Label
from textual.reactive import reactive
from textual.binding import Binding
import queue
import logging
import time

# --- Log Handling Setup ---
# Use a queue to pass log messages from the main thread to the GUI thread
log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))

# Configure root logger to use the queue handler
queue_handler = QueueHandler(log_queue)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
queue_handler.setFormatter(formatter)

# --- Proxy Input Dialog ---

class ProxyDialog(ModalScreen[dict | None]):
    """Screen with a dialog to quit."""

    CSS = """
    ProxyDialog {
        align: center middle;
    }

    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: auto auto auto auto;
        padding: 0 1;
        width: 60;
        height: auto;
        border: thick $accent;
        background: $surface;
    }

    #question {
        column-span: 2;
        height: 1;
        margin-top: 1;
        content-align: center middle;
        width: 100%;
        color: $text;
    }

    Label {
        margin: 1 0 0 1;
    }

    Input {
        margin-bottom: 1;
    }

    Button {
        width: 100%;
    }

    #ok {
        grid-column: 1;
        grid-row: 4;
    }
    #cancel {
        grid-column: 2;
        grid-row: 4;
    }
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close dialog", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Please enter proxy server details:", id="question"),
            Label("HTTP Proxy:"),
            Input(placeholder="http://user:pass@host:port", id="http_proxy"),
            Label("HTTPS Proxy:"),
            Input(placeholder="https://user:pass@host:port", id="https_proxy"),
            Button("OK", variant="primary", id="ok"),
            Button("Cancel", variant="error", id="cancel"),
            id="dialog",
        )

    def _get_proxy_dict(self) -> dict | None:
        http_proxy = self.query_one("#http_proxy", Input).value.strip()
        https_proxy = self.query_one("#https_proxy", Input).value.strip()
        if http_proxy or https_proxy:
            proxies = {}
            if http_proxy:
                proxies["http"] = http_proxy
            if https_proxy:
                proxies["https"] = https_proxy
            return proxies
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            proxies = self._get_proxy_dict()
            self.dismiss(proxies) # Return the dict or None
        else:
            self.dismiss(None) # Return None on cancel

# --- Main Launcher GUI ---

class LauncherLog(Log):
    """Log widget that polls a queue for new messages."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._poll_interval = 0.1 # Check queue every 100ms
        self._timer = self.set_interval(self._poll_interval, self._check_log_queue)

    def _check_log_queue(self):
        """Checks the queue and writes messages to the log."""
        while not log_queue.empty():
            try:
                record = log_queue.get_nowait()
                self.write_line(record)
            except queue.Empty:
                break
            except Exception as e:
                # Avoid crashing the GUI if logging fails
                self.write_line(f"Error processing log queue: {e}")

class LauncherGUI(App[None]):
    """Textual application to display launcher logs (primarily for final status/errors)."""

    TITLE = "Application Launcher Status" # Maybe a more specific title
    CSS_PATH = None
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit Launcher"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield VerticalScroll(LauncherLog(highlight=True, markup=True))
        yield Footer()

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

    def action_quit(self) -> None: # type: ignore
        """An action to quit the app."""
        # Consider if you need to signal the main thread to stop work
        self.exit(None)

if __name__ == '__main__':
    # Example usage for testing the GUI standalone
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()]) # Basic console logging for test
    log_queue.put("Log message 1")
    log_queue.put("[bold red]Error:[/bold red] Something went wrong.")
    log_queue.put("Log message 3")
    # TODO