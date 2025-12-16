"""Worker thread that orchestrates all launcher operations."""

import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .config import AppConfig, ProxySettings, load_config
from .environment import LauncherEnvironmentManager, EnvironmentError
from .proxy import discover_proxy_settings
from .runner import ScriptRunner, InitTimeoutError
from .updater import NetworkError, DownloadError, update_sources

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events sent from worker to GUI."""
    LOG = "log"
    PROGRESS = "progress"
    PROXY_REQUIRED = "proxy_required"
    INIT_TIMEOUT = "init_timeout"
    COMPLETE = "complete"
    ERROR = "error"


class ResponseType(Enum):
    """Types of responses sent from GUI to worker."""
    PROXY_SETTINGS = "proxy_settings"
    INIT_TIMEOUT_RESPONSE = "init_timeout_response"


@dataclass
class WorkerEvent:
    """Event sent from worker to GUI."""
    type: EventType
    message: str = ""
    current: int = 0
    total: int = 0
    request_id: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class GUIResponse:
    """Response sent from GUI to worker."""
    type: ResponseType
    request_id: str
    data: dict = field(default_factory=dict)


class LauncherWorker:
    """Worker thread that runs the launcher logic."""

    def __init__(
        self,
        config_path: Path,
        event_queue: queue.Queue[WorkerEvent],
        response_queue: queue.Queue[GUIResponse],
    ) -> None:
        """Initialize the worker.

        Args:
            config_path: Path to the application.yml config file
            event_queue: Queue for sending events to GUI
            response_queue: Queue for receiving responses from GUI
        """
        self.config_path = config_path
        self.event_queue = event_queue
        self.response_queue = response_queue
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._config: Optional[AppConfig] = None
        self._env_manager: Optional[LauncherEnvironmentManager] = None
        self._runner: Optional[ScriptRunner] = None

    def _send_event(self, event: WorkerEvent) -> None:
        """Send an event to the GUI."""
        self.event_queue.put(event)

    def _log(self, message: str) -> None:
        """Send a log event."""
        logger.info(message)
        self._send_event(WorkerEvent(type=EventType.LOG, message=message))

    def _progress(self, current: int, total: int, message: str) -> None:
        """Send a progress event."""
        self._send_event(WorkerEvent(
            type=EventType.PROGRESS,
            current=current,
            total=total,
            message=message,
        ))

    def _error(self, message: str) -> None:
        """Send an error event."""
        logger.error(message)
        self._send_event(WorkerEvent(type=EventType.ERROR, message=message))

    def _request_proxy(self) -> Optional[ProxySettings]:
        """Request proxy settings from GUI.

        Returns:
            ProxySettings if provided, None if cancelled
        """
        request_id = str(uuid.uuid4())
        self._send_event(WorkerEvent(
            type=EventType.PROXY_REQUIRED,
            request_id=request_id,
        ))

        # Wait for response
        try:
            response = self.response_queue.get(timeout=300)  # 5 minute timeout
            if response.type == ResponseType.PROXY_SETTINGS and response.request_id == request_id:
                data = response.data
                return ProxySettings(
                    http=data.get("http"),
                    https=data.get("https"),
                )
        except queue.Empty:
            logger.warning("Proxy settings request timed out")

        return None

    def _request_init_timeout_action(self) -> str:
        """Request action from GUI when init timeout occurs.

        Returns:
            'wait', 'reinstall', or 'exit'
        """
        request_id = str(uuid.uuid4())
        self._send_event(WorkerEvent(
            type=EventType.INIT_TIMEOUT,
            request_id=request_id,
            message=f"Init message not received within {self._config.init_timeout} seconds",
        ))

        # Wait for response
        try:
            response = self.response_queue.get(timeout=300)  # 5 minute timeout
            if response.type == ResponseType.INIT_TIMEOUT_RESPONSE and response.request_id == request_id:
                return response.data.get("action", "exit")
        except queue.Empty:
            logger.warning("Init timeout response request timed out")

        return "exit"

    def _get_proxy_settings(self) -> Optional[ProxySettings]:
        """Get proxy settings from config, discovery, or user.

        Returns:
            ProxySettings to use, or None
        """
        # Check config first
        if self._config.proxy_servers.http or self._config.proxy_servers.https:
            self._log("Using proxy settings from config")
            return self._config.proxy_servers

        # Try to discover proxy settings
        discovered = discover_proxy_settings()
        if discovered:
            self._log("Using discovered proxy settings")
            return discovered

        return None

    def _try_with_proxy_fallback(self, operation: str, func, *args, **kwargs):
        """Try an operation, falling back to proxy if it fails.

        Args:
            operation: Description of the operation for logging
            func: Function to call
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result of func

        Raises:
            Exception: If operation fails even with proxy
        """
        proxy_settings = self._get_proxy_settings()

        try:
            return func(*args, proxy_settings=proxy_settings, **kwargs)
        except NetworkError as e:
            if proxy_settings:
                # Already using proxy, ask for new settings
                self._log(f"{operation} failed with current proxy: {e}")
            else:
                self._log(f"{operation} failed (no proxy): {e}")

            # Request proxy from user
            new_proxy = self._request_proxy()
            if not new_proxy:
                raise

            # Save proxy to config
            self._config.proxy_servers = new_proxy
            self._config.save()

            # Retry with new proxy
            self._log(f"Retrying {operation} with new proxy settings")
            return func(*args, proxy_settings=new_proxy, **kwargs)

    def _run(self) -> None:
        """Main worker loop."""
        try:
            # Load configuration
            self._log("Loading configuration...")
            self._config = load_config(self.config_path)
            self._log(f"Loaded config for: {self._config.name}")

            # Initialize environment manager
            self._log("Initializing environment manager...")
            self._env_manager = LauncherEnvironmentManager()

            # Set proxy if configured
            proxy = self._get_proxy_settings()
            if proxy:
                self._env_manager.set_proxies(proxy.http, proxy.https)

            # Check for updates and download sources
            self._log("Checking for updates...")

            def progress_callback(current: int, total: int, message: str) -> None:
                self._progress(current, total, message)

            updated, version = self._try_with_proxy_fallback(
                "Update check",
                update_sources,
                self._config,
                progress_callback=progress_callback,
            )

            if updated:
                self._log(f"Downloaded new version: {version}")
            else:
                self._log(f"Using version: {version}")

            # Get or create environment
            self._log(f"Setting up environment: {self._config.env_name}")
            env = self._env_manager.get_or_create_environment(self._config)
            self._log("Environment ready")

            # Create runner
            self._runner = ScriptRunner(self._config, self._env_manager, env)

            # Run install script if defined
            if self._config.install:
                self._log("Running install script...")
                if not self._runner.run_install_script():
                    raise Exception("Install script failed")

            # Start main script
            self._log("Starting application...")
            self._runner.start(
                output_callback=lambda line: self._log(f"[app] {line}")
            )

            # Wait for init message
            if self._config.init_message:
                self._log(f"Waiting for init message: {self._config.init_message}")
                try:
                    self._runner.wait_for_init(
                        timeout_callback=self._request_init_timeout_action
                    )
                    self._log("Application initialized successfully")
                except InitTimeoutError as e:
                    if "reinstall" in str(e).lower():
                        # User requested reinstall
                        self._log("Deleting environment for reinstall...")
                        self._env_manager.delete_environment(self._config.env_name)
                        self._error("Environment deleted. Please restart the launcher.")
                        return
                    else:
                        raise

            # Complete
            self._send_event(WorkerEvent(type=EventType.COMPLETE))

        except FileNotFoundError as e:
            self._error(f"Configuration not found: {e}")
        except ValueError as e:
            self._error(f"Invalid configuration: {e}")
        except NetworkError as e:
            self._error(f"Network error: {e}")
        except DownloadError as e:
            self._error(f"Download error: {e}")
        except EnvironmentError as e:
            self._error(f"Environment error: {e}")
        except Exception as e:
            logger.exception("Unexpected error in worker")
            self._error(f"Unexpected error: {e}")

    def start(self) -> None:
        """Start the worker thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Worker already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the worker thread."""
        self._stop_event.set()

        if self._runner:
            self._runner.stop()

        if self._env_manager:
            self._env_manager.exit()

        if self._thread:
            self._thread.join(timeout=5)

    def is_running(self) -> bool:
        """Check if the worker thread is running."""
        return self._thread is not None and self._thread.is_alive()


def create_queues() -> tuple[queue.Queue[WorkerEvent], queue.Queue[GUIResponse]]:
    """Create the event and response queues.

    Returns:
        Tuple of (event_queue, response_queue)
    """
    return queue.Queue(), queue.Queue()
