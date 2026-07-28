"""Worker thread that orchestrates all launcher operations."""

import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import AppConfig, ProxySettings, load_config
from .environment import (
    LauncherEnvironmentManager,
    EnvironmentError,
    compute_dependency_hash,
    compute_project_install_fingerprint,
)
from .installation import (
    InstallationError,
    InstallationRootKind,
    default_installation_root,
    initialize_installation_root,
    inspect_installation_root,
    replace_installation_root,
)
from .proxy import discover_proxy_settings
from .runner import ScriptRunner, InitTimeoutError, RunnerError
from .updater import HTTPStatusError, NetworkError, DownloadError, UpdaterError, update_sources
from .state import LauncherState, StateStorageError, enable_portable_state

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events sent from worker to GUI."""
    LOG = "log"
    PROGRESS = "progress"
    PROXY_REQUIRED = "proxy_required"
    INIT_TIMEOUT = "init_timeout"
    INSTALL_LOCATION_REQUIRED = "install_location_required"
    EXISTING_INSTALLATION = "existing_installation"
    STATE_STORAGE_REQUIRED = "state_storage_required"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    ERROR = "error"


class ResponseType(Enum):
    """Types of responses sent from GUI to worker."""
    PROXY_SETTINGS = "proxy_settings"
    INIT_TIMEOUT_RESPONSE = "init_timeout_response"
    INSTALL_LOCATION_RESPONSE = "install_location_response"
    EXISTING_INSTALLATION_RESPONSE = "existing_installation_response"
    STATE_STORAGE_RESPONSE = "state_storage_response"


class LauncherCancelled(Exception):
    """Raised when the user cancels an interactive launcher decision."""


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
        self._state: Optional[LauncherState] = None
        self._env_manager: Optional[LauncherEnvironmentManager] = None
        self._runner: Optional[ScriptRunner] = None
        self._completed = False
        self._failed = False
        self._error_message: Optional[str] = None
        self._last_proxy_remember_password = False

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
        self._failed = True
        self._error_message = message
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
                self._last_proxy_remember_password = bool(data.get("remember_password"))
                return ProxySettings(
                    http=data.get("http"),
                    https=data.get("https"),
                    ssl_cert_file=data.get("ssl_cert_file"),
                )
        except queue.Empty:
            logger.warning("Proxy settings request timed out")

        return None

    def _request_init_timeout_action(self) -> str:
        """Request action from GUI when init timeout occurs.

        Returns:
            'wait', 'reinstall', or 'exit'
        """
        assert self._config is not None, "Config not loaded"
        request_id = str(uuid.uuid4())
        self._send_event(WorkerEvent(
            type=EventType.INIT_TIMEOUT,
            request_id=request_id,
            message=(
                "The application started but did not report that it finished "
                f"initializing within {self._config.init_timeout} seconds. "
                "You can keep waiting if startup is slow. Reinstalling recreates "
                "the local environment and may fix a corrupted local install, but "
                "it will not fix a broken release; publish a fixed release and "
                "restart the launcher for that case."
            ),
        ))

        # Wait for response
        try:
            response = self.response_queue.get(timeout=300)  # 5 minute timeout
            if response.type == ResponseType.INIT_TIMEOUT_RESPONSE and response.request_id == request_id:
                return response.data.get("action", "exit")
        except queue.Empty:
            logger.warning("Init timeout response request timed out")

        return "exit"

    def _load_state(self) -> LauncherState:
        """Load writable state, offering explicit portable storage if necessary."""
        assert self._config is not None, "Config not loaded"
        try:
            return LauncherState.for_app(self._config.name)
        except StateStorageError as exc:
            if not exc.portable_dir or not exc.portable_available:
                raise
            request_id = str(uuid.uuid4())
            self._send_event(
                WorkerEvent(
                    type=EventType.STATE_STORAGE_REQUIRED,
                    request_id=request_id,
                    message=str(exc),
                    data={"portable_path": str(exc.portable_dir)},
                )
            )
            response = self._wait_for_response(request_id, ResponseType.STATE_STORAGE_RESPONSE)
            if not response or response.data.get("action") != "portable":
                raise LauncherCancelled("State storage selection cancelled")
            portable_dir = enable_portable_state(self._config.name)
            return LauncherState.for_app(self._config.name, state_dir=portable_dir)

    def _configure_installation(self) -> Path:
        """Resolve, validate, and persist the app runtime installation root."""
        assert self._config is not None, "Config not loaded"
        assert self._state is not None, "State not loaded"

        if self._state.installation_root:
            root = Path(self._state.installation_root).expanduser().resolve()
            inspection = inspect_installation_root(root, self._config.name)
            if inspection.kind == InstallationRootKind.CONFLICT:
                raise InstallationError(inspection.message)
            if inspection.kind == InstallationRootKind.NEW:
                initialize_installation_root(root, self._config.name)
            self._config.use_installation_root(root)
            return root

        root = default_installation_root(self._config)
        if self._config.ask_install_location:
            request_id = str(uuid.uuid4())
            self._send_event(
                WorkerEvent(
                    type=EventType.INSTALL_LOCATION_REQUIRED,
                    request_id=request_id,
                    message=f"Choose where to install {self._config.name}.",
                    data={"default_path": str(root)},
                )
            )
            response = self._wait_for_response(request_id, ResponseType.INSTALL_LOCATION_RESPONSE)
            selected = response.data.get("path") if response else None
            if not selected:
                raise LauncherCancelled("Installation destination selection cancelled")
            root = Path(selected).expanduser().resolve()

        inspection = inspect_installation_root(root, self._config.name)
        if inspection.kind == InstallationRootKind.CONFLICT:
            raise InstallationError(inspection.message)
        if inspection.kind == InstallationRootKind.EXISTING:
            request_id = str(uuid.uuid4())
            self._send_event(
                WorkerEvent(
                    type=EventType.EXISTING_INSTALLATION,
                    request_id=request_id,
                    message=f"An existing {self._config.name} installation was found at {root}.",
                    data={"path": str(root)},
                )
            )
            response = self._wait_for_response(request_id, ResponseType.EXISTING_INSTALLATION_RESPONSE)
            action = response.data.get("action", "cancel") if response else "cancel"
            if action == "cancel":
                raise LauncherCancelled("Existing installation selection cancelled")
            if action == "replace":
                replace_installation_root(root, self._config.name)
                self._state.clear_installation_fingerprints()
            elif action != "use":
                raise LauncherCancelled("Existing installation selection cancelled")
        else:
            initialize_installation_root(root, self._config.name)

        self._state.installation_root = str(root)
        self._state.save()
        self._config.use_installation_root(root)
        return root

    def _wait_for_response(
        self,
        request_id: str,
        response_type: ResponseType,
    ) -> Optional[GUIResponse]:
        """Wait for the matching response to an interactive request."""
        try:
            response = self.response_queue.get(timeout=300)
        except queue.Empty:
            logger.warning("%s request timed out", response_type.value)
            return None
        if response.type == response_type and response.request_id == request_id:
            return response
        logger.warning("Ignoring mismatched response for request %s", request_id)
        return None

    def _get_proxy_settings(self) -> Optional[ProxySettings]:
        """Get proxy settings from config, discovery, or user.

        Returns:
            ProxySettings to use, or None
        """
        # Check config first
        assert self._config is not None, "Config not loaded"
        if self._state:
            state_proxy = self._state.proxy_settings()
            if state_proxy:
                self._log("Using proxy settings from runtime state")
                return state_proxy

        if (
            self._config.proxy_servers.http
            or self._config.proxy_servers.https
            or self._config.proxy_servers.ssl_cert_file
        ):
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

            # Save only runtime proxy metadata. Passwords are stored in the
            # keychain only when the user opted in, otherwise they remain in memory.
            if self._state:
                self._state.remember_proxy_settings(
                    new_proxy,
                    remember_password=self._last_proxy_remember_password,
                )

            # Retry with new proxy
            self._log(f"Retrying {operation} with new proxy settings")
            return func(*args, proxy_settings=new_proxy, **kwargs)

    def _cleanup_after_failure(self) -> None:
        """Terminate launcher-owned resources after a failed or cancelled launch."""
        if self._runner:
            self._runner.stop()
        if self._env_manager:
            self._env_manager.exit()

    def _run(self) -> None:  # pyright: ignore[reportGeneralTypeIssues]
        """Main worker loop."""
        try:
            # Load configuration
            self._log("Loading configuration...")
            self._config = load_config(self.config_path)
            self._state = self._load_state()
            installation_root = self._configure_installation()
            if self._config.auto_update and self._state.version:
                self._config.version = self._state.version
            self._log(f"Loaded config for: {self._config.name}")
            self._log(f"Using installation root: {installation_root}")

            # Initialize environment manager
            self._log("Initializing environment manager...")
            self._env_manager = LauncherEnvironmentManager(
                wetlands_path=installation_root / "wetlands"
            )

            # Set proxy if configured
            proxy = self._get_proxy_settings()
            if proxy:
                self._env_manager.set_proxies(proxy.http, proxy.https, proxy.ssl_cert_file)

            # Check for updates and download sources
            self._log("Checking for updates...")

            def progress_callback(current: int, total: int, message: str) -> None:
                self._progress(current, total, message)

            updated, version = self._try_with_proxy_fallback(
                "Update check",
                update_sources,
                self._config,
                progress_callback=progress_callback,
                state=self._state,
            )

            if updated:
                self._log(f"Downloaded new version: {version}")
            else:
                self._log(f"Using version: {version}")

            # Check if environment exists before creating
            env_existed = self._env_manager.environment_exists(self._config.env_name)
            dependency_hash = compute_dependency_hash(self._config)
            project_install_fingerprint = None
            project_install_managed_by_environment = False
            if self._config.entrypoint.mode == "project":
                project_install_fingerprint = compute_project_install_fingerprint(self._config, version)
                project_install_managed_by_environment = self._env_manager.project_install_managed_by_environment(
                    self._config
                )
            if (
                env_existed
                and self._state
                and self._state.dependency_hash
                and self._state.dependency_hash != dependency_hash
            ):
                self._log("Dependency inputs changed; recreating environment...")
                self._env_manager.delete_environment(self._config.env_name)
                env_existed = False
            if (
                project_install_managed_by_environment
                and env_existed
                and (
                    not self._state
                    or self._state.project_install_fingerprint != project_install_fingerprint
                )
            ):
                self._log("Project package inputs changed; recreating environment...")
                self._env_manager.delete_environment(self._config.env_name)
                env_existed = False

            # Get or create environment
            self._log(f"Setting up environment: {self._config.env_name}")
            env = self._env_manager.get_or_create_environment(self._config)
            self._log("Environment ready")

            # Create runner
            self._runner = ScriptRunner(self._config, self._env_manager, env)

            # Run install script if:
            # - environment was just created, OR
            # - new sources were downloaded and reinstall_on_update is enabled
            should_run_install = self._config.install and (
                not env_existed or (updated and self._config.reinstall_on_update)
            )
            if should_run_install:
                if updated and self._config.reinstall_on_update and env_existed:
                    self._log("Running install script (reinstall_on_update enabled)...")
                else:
                    self._log("Running install script...")
                if not self._runner.run_install_script():
                    raise Exception("Install script failed")

            if self._config.entrypoint.mode == "project":
                self._log("Project package install is managed by environment dependencies")

            if self._state:
                self._state.version = version
                self._state.dependency_hash = dependency_hash
                if project_install_fingerprint:
                    self._state.project_install_fingerprint = project_install_fingerprint
                self._state.save()

            # Start the configured entrypoint
            self._log("Starting application...")
            process = self._runner.start(
                output_callback=lambda line: self._log(f"[app] {line}")
            )
            process_id = getattr(process, "pid", None)
            if process_id:
                self._log(f"Application process started with PID {process_id}")

            # Wait for init message
            if self._config.init_message:
                self._log(f"Waiting for init message: {self._config.init_message}")
                try:
                    initialized = self._runner.wait_for_init(
                        timeout_callback=self._request_init_timeout_action
                    )
                    if not initialized:
                        raise InitTimeoutError("Application initialization could not be verified")
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
            else:
                self._runner.ensure_still_running()
                self._log("No init_message configured; launcher will exit and leave the application running.")

            # Complete
            self._completed = True
            self._send_event(WorkerEvent(type=EventType.COMPLETE))

        except FileNotFoundError as e:
            self._error(f"Configuration not found: {e}")
        except LauncherCancelled as e:
            logger.info("%s", e)
            self._send_event(WorkerEvent(type=EventType.CANCELLED, message=str(e)))
        except ValueError as e:
            self._error(f"Invalid configuration: {e}")
        except StateStorageError as e:
            self._error(f"State storage error: {e}")
        except InstallationError as e:
            self._error(f"Installation error: {e}")
        except HTTPStatusError as e:
            self._error(f"Update error: {e}")
        except UpdaterError as e:
            self._error(f"Update error: {e}")
        except NetworkError as e:
            self._error(f"Network error: {e}")
        except DownloadError as e:
            self._error(f"Download error: {e}")
        except EnvironmentError as e:
            self._error(f"Environment error: {e}")
        except RunnerError as e:
            self._error(f"Launch error: {e}")
        except Exception as e:
            logger.exception("Unexpected error in worker")
            self._error(f"Unexpected error: {e}")
        finally:
            if self._failed or self._stop_event.is_set():
                self._cleanup_after_failure()

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

        if self._runner and not self._completed:
            self._runner.stop()

        if self._env_manager and not self._completed:
            self._env_manager.exit()

        if self._thread:
            self._thread.join(timeout=5)

    def is_running(self) -> bool:
        """Check if the worker thread is running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def completed(self) -> bool:
        """Whether the launcher completed and transferred ownership to the app."""
        return self._completed

    @property
    def failed(self) -> bool:
        """Whether the worker failed."""
        return self._failed

    @property
    def error_message(self) -> Optional[str]:
        """Return the worker error message, if any."""
        return self._error_message


def create_queues() -> tuple[queue.Queue[WorkerEvent], queue.Queue[GUIResponse]]:
    """Create the event and response queues.

    Returns:
        Tuple of (event_queue, response_queue)
    """
    return queue.Queue(), queue.Queue()
