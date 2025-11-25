"""Console-based GUI implementation."""

import queue
import sys
import time
from typing import TYPE_CHECKING

from gui.base_gui import BaseGUI

if TYPE_CHECKING:
    from launcher import Launcher


class ConsoleGUI(BaseGUI):
    """Simple console-based GUI using print and input."""

    def show_proxy_dialog(self) -> dict:
        """Show proxy settings dialog in console.

        Returns:
            Dictionary with 'http' and 'https' proxy URLs
        """
        print("\n" + "=" * 60)
        print("Proxy Configuration Required")
        print("=" * 60)

        http_proxy = input("HTTP Proxy URL (leave empty if none): ").strip()
        https_proxy = input("HTTPS Proxy URL (leave empty if none): ").strip()

        print("=" * 60 + "\n")

        return {
            "http": http_proxy if http_proxy else None,
            "https": https_proxy if https_proxy else None,
        }

    def run(self) -> None:
        """Run console GUI.

        Displays logs and progress to the console while monitoring
        the event queue for updates from the worker thread.
        """
        print("\nLauncher Starting...\n")

        complete = False
        error = False

        while not complete:
            try:
                event = self.event_queue.get(timeout=0.1)

                if event["type"] == "log":
                    print(f"[LOG] {event['message']}")

                elif event["type"] == "progress":
                    current = event.get("current", 0)
                    total = event.get("total", 100)
                    percentage = (current / total * 100) if total > 0 else 0
                    bar_length = 40
                    filled = int(bar_length * current / total) if total > 0 else 0
                    bar = "█" * filled + "░" * (bar_length - filled)
                    print(f"[PROGRESS] {bar} {percentage:.1f}%")

                elif event["type"] == "error":
                    print(f"[ERROR] {event['message']}")
                    error = True

                elif event["type"] == "complete":
                    complete = True
                    if event.get("error"):
                        error = True

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
                # No event available, continue waiting
                pass
            except KeyboardInterrupt:
                print("\nLauncher cancelled by user")
                break

        if error:
            print("\nLauncher completed with errors")
            sys.exit(1)
        else:
            print("\nLauncher completed successfully")
