"""Worker thread for launcher operations."""

import queue
import uuid
from typing import Optional

from launcher import Launcher
from proxy import get_proxy_settings, ProxySettings, apply_proxy_to_requests


def launcher_worker(
    config_path: str,
    event_queue: queue.Queue,
    response_queue: queue.Queue,
    path_override: Optional[str] = None,
) -> None:
    """Worker thread function for running launcher operations.

    This function runs in a separate thread and handles:
    1. Loading launcher configuration
    2. Checking and downloading updates
    3. Setting up environment and running application
    4. Communicating with GUI via queues

    Args:
        config_path: Path to application.yml
        event_queue: Queue for sending events to GUI
        response_queue: Queue for receiving responses from GUI
        path_override: Optional override for the path attribute from config
    """
    try:
        event_queue.put({"type": "log", "message": "Initializing launcher..."})

        # Load launcher
        launcher = Launcher(config_path, path_override=path_override)

        # Get proxy settings
        proxy_settings = get_proxy_settings(config_path)
        if proxy_settings.http or proxy_settings.https:
            event_queue.put(
                {
                    "type": "log",
                    "message": f"Using proxy: {proxy_settings.http or proxy_settings.https}",
                }
            )

        event_queue.put({"type": "log", "message": "Getting current version..."})
        version = launcher.get_current_version()
        event_queue.put({"type": "log", "message": f"Current version: {version}"})

        # Check if sources exist
        if not launcher.sources_exist(version):
            event_queue.put(
                {"type": "log", "message": f"Downloading sources for {version}..."}
            )
            event_queue.put({"type": "progress", "current": 0, "total": 100})

            try:
                launcher.download_sources(version)
                event_queue.put(
                    {"type": "log", "message": "Sources downloaded successfully"}
                )
                event_queue.put(
                    {"type": "progress", "current": 50, "total": 100}
                )
            except Exception as e:
                event_queue.put(
                    {"type": "error", "message": f"Failed to download sources: {e}"}
                )
                raise
        else:
            event_queue.put(
                {"type": "log", "message": f"Sources found for {version}"}
            )

        # Setup environment
        event_queue.put(
            {"type": "log", "message": "Setting up Python environment..."}
        )
        env = launcher.setup_environment(version)
        event_queue.put(
            {"type": "log", "message": "Environment setup complete"}
        )
        event_queue.put({"type": "progress", "current": 75, "total": 100})

        # Run application
        event_queue.put(
            {"type": "log", "message": "Launching application..."}
        )
        launcher.run_app(env)
        event_queue.put({"type": "progress", "current": 100, "total": 100})
        event_queue.put({"type": "log", "message": "Application launched successfully"})
        event_queue.put({"type": "complete"})

    except Exception as e:
        event_queue.put(
            {"type": "error", "message": f"Launcher error: {str(e)}"}
        )
        event_queue.put({"type": "complete", "error": True})


def request_proxy_settings(
    event_queue: queue.Queue,
    response_queue: queue.Queue,
    timeout: int = 30,
) -> Optional[ProxySettings]:
    """Request proxy settings from GUI.

    Args:
        event_queue: Queue for sending request to GUI
        response_queue: Queue for receiving response from GUI
        timeout: Timeout in seconds for waiting for response

    Returns:
        ProxySettings with user-entered values, or None if timeout
    """
    request_id = str(uuid.uuid4())
    event_queue.put({"type": "proxy_required", "request_id": request_id})

    try:
        response = response_queue.get(timeout=timeout)
        if response.get("request_id") == request_id:
            data = response.get("data", {})
            return ProxySettings(
                http=data.get("http"),
                https=data.get("https"),
            )
    except queue.Empty:
        pass

    return None
