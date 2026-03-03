"""Base GUI interface for the launcher application."""

import queue
import threading
from abc import ABC, abstractmethod
from typing import Optional

from ..worker import WorkerEvent, GUIResponse, EventType, ResponseType


class BaseGUI(ABC):
    """Abstract base class for GUI implementations.

    All GUI implementations must inherit from this class and implement
    the abstract methods.
    """

    def __init__(
        self,
        event_queue: queue.Queue[WorkerEvent],
        response_queue: queue.Queue[GUIResponse],
        app_name: str = "Launcher",
    ) -> None:
        """Initialize the GUI.

        Args:
            event_queue: Queue for receiving events from worker
            response_queue: Queue for sending responses to worker
            app_name: Application name to display
        """
        self.event_queue = event_queue
        self.response_queue = response_queue
        self.app_name = app_name
        self._visible = False
        self._completed = False
        self._error_message: Optional[str] = None

    @abstractmethod
    def _create_window(self) -> None:
        """Create the GUI window/widgets.

        Called once when the GUI is first shown.
        """
        pass

    @abstractmethod
    def _update_progress(self, current: int, total: int, message: str) -> None:
        """Update the progress display.

        Args:
            current: Current progress value
            total: Total progress value (0 if indeterminate)
            message: Progress message
        """
        pass

    @abstractmethod
    def _append_log(self, message: str) -> None:
        """Append a message to the log display.

        Args:
            message: Log message to append
        """
        pass

    @abstractmethod
    def _show_proxy_dialog(self, request_id: str) -> None:
        """Show the proxy settings dialog.

        When the user submits proxy settings, call _submit_proxy_response()
        with the request_id and the http/https proxy URLs.

        Args:
            request_id: Request ID to include in response
        """
        pass

    @abstractmethod
    def _show_init_timeout_dialog(self, request_id: str, message: str) -> None:
        """Show the init timeout dialog.

        When the user makes a choice, call _submit_init_timeout_response()
        with the request_id and action ('wait', 'reinstall', or 'exit').

        Args:
            request_id: Request ID to include in response
            message: Message to display
        """
        pass

    @abstractmethod
    def _show_error(self, message: str) -> None:
        """Display an error message.

        Args:
            message: Error message to display
        """
        pass

    @abstractmethod
    def _show_complete(self) -> None:
        """Handle completion of the launcher process."""
        pass

    @abstractmethod
    def _process_events_once(self) -> bool:
        """Process pending GUI events once.

        This should process any pending UI events and return.
        Called in a loop by run().

        Returns:
            False if the GUI should exit, True otherwise
        """
        pass

    @abstractmethod
    def show(self) -> None:
        """Show the GUI window."""
        pass

    @abstractmethod
    def hide(self) -> None:
        """Hide the GUI window."""
        pass

    @abstractmethod
    def destroy(self) -> None:
        """Destroy the GUI and clean up resources."""
        pass

    def _submit_proxy_response(
        self,
        request_id: str,
        http_proxy: Optional[str],
        https_proxy: Optional[str],
        ssl_cert_file: Optional[str] = None,
    ) -> None:
        """Submit proxy settings response to worker.

        Args:
            request_id: Request ID from the proxy_required event
            http_proxy: HTTP proxy URL or None
            https_proxy: HTTPS proxy URL or None
            ssl_cert_file: Path to a custom CA certificate file or None
        """
        response = GUIResponse(
            type=ResponseType.PROXY_SETTINGS,
            request_id=request_id,
            data={
                "http": http_proxy,
                "https": https_proxy,
                "ssl_cert_file": ssl_cert_file,
            },
        )
        self.response_queue.put(response)

    def _submit_init_timeout_response(self, request_id: str, action: str) -> None:
        """Submit init timeout action response to worker.

        Args:
            request_id: Request ID from the init_timeout event
            action: 'wait', 'reinstall', or 'exit'
        """
        response = GUIResponse(
            type=ResponseType.INIT_TIMEOUT_RESPONSE,
            request_id=request_id,
            data={"action": action},
        )
        self.response_queue.put(response)

    def _check_events(self) -> None:
        """Check for and handle events from the worker.

        Should be called periodically (e.g., every 100ms).
        """
        try:
            while True:
                event = self.event_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass

    def _handle_event(self, event: WorkerEvent) -> None:
        """Handle a single event from the worker.

        Args:
            event: The event to handle
        """
        if event.type == EventType.LOG:
            self._append_log(event.message)
        elif event.type == EventType.PROGRESS:
            self._update_progress(event.current, event.total, event.message)
        elif event.type == EventType.PROXY_REQUIRED:
            self._show_proxy_dialog(event.request_id)
        elif event.type == EventType.INIT_TIMEOUT:
            self._show_init_timeout_dialog(event.request_id, event.message)
        elif event.type == EventType.ERROR:
            self._error_message = event.message
            self._show_error(event.message)
        elif event.type == EventType.COMPLETE:
            self._completed = True
            self._show_complete()

    def run(self) -> None:
        """Run the GUI main loop.

        This should be called from the main thread.
        Creates the window if not already created, then enters the event loop.
        """
        if not self._visible:
            self._create_window()
            self.show()
            self._visible = True

        # Main event loop
        while self._process_events_once():
            self._check_events()

    @property
    def is_completed(self) -> bool:
        """Check if the launcher completed successfully."""
        return self._completed

    @property
    def error_message(self) -> Optional[str]:
        """Get the error message if an error occurred."""
        return self._error_message
