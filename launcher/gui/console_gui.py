"""Console (no GUI) implementation for the launcher."""

import queue
import sys
import time
from typing import Optional

from .base import BaseGUI
from ..worker import WorkerEvent, GUIResponse, EventType


class ConsoleGUI(BaseGUI):
    """Console-based interface for the launcher.

    Uses print() for output and input() for user interaction.
    No graphical interface - runs entirely in the terminal.
    """

    def __init__(
        self,
        event_queue: queue.Queue[WorkerEvent],
        response_queue: queue.Queue[GUIResponse],
        app_name: str = "Launcher",
    ) -> None:
        super().__init__(event_queue, response_queue, app_name)
        self._running = True
        self._last_progress_message = ""

    def _create_window(self) -> None:
        """Initialize console output."""
        print(f"\n{'=' * 60}")
        print(f"  {self.app_name} - Launcher")
        print(f"{'=' * 60}\n")

    def _update_progress(self, current: int, total: int, message: str) -> None:
        """Update progress display."""
        if message != self._last_progress_message:
            if total > 0:
                percentage = (current / total) * 100
                bar_length = 30
                filled = int(bar_length * current / total)
                bar = "=" * filled + "-" * (bar_length - filled)
                print(f"\r[{bar}] {percentage:5.1f}% - {message}", end="", flush=True)
            else:
                print(f"\r[...] {message}", end="", flush=True)
            self._last_progress_message = message

    def _append_log(self, message: str) -> None:
        """Print log message."""
        # Clear progress line if present
        print(f"\r{' ' * 80}\r", end="")
        print(f"  {message}")
        # Reprint progress if we had one
        self._last_progress_message = ""

    def _show_proxy_dialog(self, request_id: str) -> None:
        """Prompt for proxy settings."""
        print("\n" + "-" * 40)
        print("Proxy Settings Required")
        print("-" * 40)
        print("Enter proxy URLs (leave empty to skip)")
        print("Format: http://username:password@proxy.example.com:8080\n")

        try:
            http_proxy = input("HTTP Proxy: ").strip() or None
            https_proxy = input("HTTPS Proxy: ").strip() or None
            ssl_cert_file = input("SSL Certificate path (optional): ").strip() or None
            self._submit_proxy_response(request_id, http_proxy, https_proxy, ssl_cert_file)
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled")
            self._submit_proxy_response(request_id, None, None)

        print("-" * 40 + "\n")

    def _show_init_timeout_dialog(self, request_id: str, message: str) -> None:
        """Prompt for init timeout action."""
        print("\n" + "-" * 40)
        print("Initialization Timeout")
        print("-" * 40)
        print(f"{message}\n")
        print("Options:")
        print("  1. Wait more")
        print("  2. Reinstall (delete environment and restart)")
        print("  3. Exit")

        try:
            choice = input("\nEnter choice (1/2/3): ").strip()
            if choice == "1":
                action = "wait"
            elif choice == "2":
                action = "reinstall"
            else:
                action = "exit"
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            action = "exit"

        self._submit_init_timeout_response(request_id, action)
        print("-" * 40 + "\n")

    def _show_error(self, message: str) -> None:
        """Display error message."""
        print(f"\r{' ' * 80}\r", end="")
        print(f"\n{'!' * 60}")
        print(f"ERROR: {message}")
        print(f"{'!' * 60}\n")
        self._running = False

    def _show_complete(self) -> None:
        """Handle completion."""
        print(f"\r{' ' * 80}\r", end="")
        print(f"\n{'=' * 60}")
        print("  Launcher complete. Application is running.")
        print(f"{'=' * 60}\n")
        self._running = False

    def _process_events_once(self) -> bool:
        """Process events once.

        Returns:
            True to continue, False to exit
        """
        if not self._running:
            return False

        # Small sleep to avoid busy waiting
        time.sleep(0.1)
        return True

    def show(self) -> None:
        """No-op for console."""
        pass

    def hide(self) -> None:
        """No-op for console."""
        pass

    def destroy(self) -> None:
        """Stop the console loop."""
        self._running = False

    def run(self) -> None:
        """Run the console event loop."""
        if not self._visible:
            self._create_window()
            self._visible = True

        try:
            while self._process_events_once():
                self._check_events()
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            self._running = False
