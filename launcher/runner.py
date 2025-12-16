"""Script execution and initialization monitoring."""

import logging
import subprocess
import threading
from typing import Callable, Optional

from wetlands.environment import Environment

from .config import AppConfig
from .environment import LauncherEnvironmentManager

logger = logging.getLogger(__name__)

# Type aliases
OutputCallback = Callable[[str], None]
InitTimeoutCallback = Callable[[], str]  # Returns 'wait', 'reinstall', or 'exit'


class RunnerError(Exception):
    """Exception for runner-related errors."""
    pass


class InitTimeoutError(RunnerError):
    """Raised when init message is not received within timeout."""
    pass


class ScriptRunner:
    """Runs the main script and monitors for initialization."""

    def __init__(
        self,
        config: AppConfig,
        env_manager: LauncherEnvironmentManager,
        env: Environment,
    ) -> None:
        """Initialize the script runner.

        Args:
            config: Application configuration
            env_manager: The environment manager
            env: The Wetlands environment to run in
        """
        self.config = config
        self.env_manager = env_manager
        self.env = env
        self._process: Optional[subprocess.Popen] = None
        self._init_received = threading.Event()
        self._output_lines: list[str] = []
        self._lock = threading.Lock()

    def run_install_script(self) -> bool:
        """Run the install script if defined.

        Returns:
            True if install script ran successfully or wasn't defined
        """
        install_path = self.config.install_script_path
        if not install_path:
            logger.info("No install script defined")
            return True

        if not install_path.exists():
            logger.warning(f"Install script not found: {install_path}")
            return True

        logger.info(f"Running install script: {install_path}")
        try:
            # Use env.execute_commands as per specs.md
            process = self.env.execute_commands(
                commands=[f'python "{install_path}"'],
                wait=True,
            )

            if process.returncode != 0:
                logger.error(f"Install script failed with return code {process.returncode}")
                return False

            logger.info("Install script completed successfully")
            return True
        except Exception as e:
            logger.error(f"Install script failed: {e}")
            return False

    def start(
        self,
        output_callback: Optional[OutputCallback] = None,
    ) -> subprocess.Popen:
        """Start the main script.

        Args:
            output_callback: Optional callback for stdout lines

        Returns:
            The subprocess.Popen instance
        """
        main_script_path = self.config.main_script_path
        if not main_script_path.exists():
            raise RunnerError(f"Main script not found: {main_script_path}")

        logger.info(f"Starting main script: {main_script_path}")

        # Wrap the callback to capture output and check for init message
        def wrapped_callback(line: str) -> None:
            with self._lock:
                self._output_lines.append(line)

            # Check for init message
            if self.config.init_message and self.config.init_message in line:
                logger.info(f"Init message received: {self.config.init_message}")
                self._init_received.set()

            if output_callback:
                output_callback(line)

        # Use env.execute_commands as per specs.md
        self._process = self.env.execute_commands(
            commands=[f'python -u "{main_script_path}"'],
            wait=False,
        )

        # Start a thread to read output using ProcessLogger
        process_logger = self.env_manager.manager.get_process_logger(self._process)
        if process_logger:
            output_thread = threading.Thread(
                target=self._read_output_from_logger,
                args=(process_logger, wrapped_callback),
                daemon=True,
            )
            output_thread.start()

        return self._process

    def _read_output_from_logger(self, process_logger, callback: OutputCallback) -> None:
        """Read process output using ProcessLogger.

        Args:
            process_logger: Wetlands ProcessLogger instance
            callback: Callback to call for each line
        """
        try:
            for line in process_logger:
                if line:
                    callback(line)
        except Exception as e:
            logger.error(f"Error reading process output: {e}")

    def wait_for_init(
        self,
        timeout_callback: Optional[InitTimeoutCallback] = None,
    ) -> bool:
        """Wait for the init message.

        Args:
            timeout_callback: Callback when timeout occurs.
                            Should return 'wait' to continue waiting,
                            'reinstall' to request reinstall, or 'exit' to abort.

        Returns:
            True if init message received, False otherwise

        Raises:
            InitTimeoutError: If timeout occurs and no callback or callback returns 'exit'
        """
        if not self.config.init_message:
            logger.info("No init message configured, skipping wait")
            return True

        timeout = self.config.init_timeout

        while True:
            # Wait for init message with timeout
            if self._init_received.wait(timeout=timeout):
                return True

            # Check if process has exited
            if self._process and self._process.poll() is not None:
                logger.error(f"Process exited with code {self._process.returncode} before init message")
                raise InitTimeoutError(
                    f"Process exited (code {self._process.returncode}) before init message was received"
                )

            # Timeout occurred
            logger.warning(f"Init message not received within {timeout} seconds")

            if timeout_callback:
                action = timeout_callback()
                if action == "wait":
                    logger.info("User chose to wait longer")
                    continue
                elif action == "reinstall":
                    logger.info("User chose to reinstall")
                    self.stop()
                    raise InitTimeoutError("User requested reinstall")
                else:  # exit
                    logger.info("User chose to exit")
                    self.stop()
                    raise InitTimeoutError("User requested exit")
            else:
                raise InitTimeoutError(
                    f"Init message '{self.config.init_message}' not received within {timeout} seconds"
                )

    def stop(self) -> None:
        """Stop the running process."""
        if self._process:
            logger.info("Stopping process")
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Process did not terminate, killing")
                self._process.kill()
            self._process = None

    @property
    def is_running(self) -> bool:
        """Check if the process is still running."""
        return self._process is not None and self._process.poll() is None

    @property
    def return_code(self) -> Optional[int]:
        """Get the process return code, or None if still running."""
        if self._process:
            return self._process.poll()
        return None

    @property
    def output_lines(self) -> list[str]:
        """Get all captured output lines."""
        with self._lock:
            return self._output_lines.copy()
