"""Abstract base class for GUI implementations."""

import queue
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher import Launcher


class BaseGUI(ABC):
    """Abstract base class for all GUI implementations.

    Defines the interface for GUI implementations and handles
    queue-based communication with the worker thread.
    """

    def __init__(
        self,
        launcher: "Launcher",
        event_queue: queue.Queue,
        response_queue: queue.Queue,
    ):
        """Initialize GUI with launcher and communication queues.

        Args:
            launcher: Launcher instance
            event_queue: Queue for receiving events from worker thread
            response_queue: Queue for sending responses to worker thread
        """
        self.launcher = launcher
        self.event_queue = event_queue
        self.response_queue = response_queue

    @abstractmethod
    def show_proxy_dialog(self) -> dict:
        """Show dialog for user to enter proxy settings.

        Returns:
            Dictionary with 'http' and 'https' proxy URLs
        """
        pass

    @abstractmethod
    def run(self) -> None:
        """Run the GUI main loop.

        This should start the GUI and handle all events from the
        event_queue until the application is complete.
        """
        pass
