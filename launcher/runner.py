"""Script execution and initialization monitoring."""

import logging
import shlex
import subprocess
import threading
import time
from typing import Callable, Optional

from wetlands.environment import Environment

from .config import AppConfig
from .environment import LauncherEnvironmentManager
from .paths import get_runtime_data_dir

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
    """Runs the configured entrypoint and monitors initialization."""

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
        self._process_logger = None
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
        """Start the configured entrypoint.

        Args:
            output_callback: Optional callback for stdout lines

        Returns:
            The subprocess.Popen instance
        """
        if self.config.entrypoint.mode == "script":
            command = self._script_command()
            logger.info(f"Starting script entrypoint: {self.config.script_path}")
        elif self.config.entrypoint.mode == "module":
            command = self._module_command()
            logger.info(f"Starting module entrypoint: {self.config.entrypoint.module}")
        else:
            command = self._project_command()
            logger.info(f"Starting project command: {self.config.entrypoint.command}")

        working_directory = self.config.working_directory_path
        if not working_directory.exists():
            raise RunnerError(
                f"Configured working directory not found: {working_directory}\n"
                "Launcher uses `working_directory` when set. Otherwise, it defaults "
                "to the directory containing `configuration`, or to the downloaded "
                "sources directory when `configuration: null`."
            )

        def on_output(line: str, _context: dict) -> None:
            with self._lock:
                self._output_lines.append(line)
            if output_callback:
                output_callback(line)

        self._process = self.env.execute_commands(
            commands=[command],
            popen_kwargs=self._launch_popen_kwargs(),
            wait=False,
        )

        # Subscribe to process output using ProcessLogger
        self._process_logger = self.env_manager.get_process_logger(self._process)
        if self._process_logger:
            self._process_logger.subscribe(on_output, include_history=False)

        return self._process

    def _script_command(self) -> str:
        script_path = self.config.script_path
        if script_path is None:
            raise RunnerError("Script entrypoint is not configured")
        if not script_path.exists():
            raise RunnerError(
                f"Configured script entrypoint not found: {script_path}\n"
                f"Launcher looked for `entrypoint.script: {self.config.entrypoint.script}` "
                "inside the downloaded sources at "
                f"{self.config.sources_path}.\n"
                "Update `entrypoint.script` in packaging/launcher/application.yml "
                "to the Python file that starts your app, or include that file in "
                "the release archive."
            )
        return f'python -u "{self._write_script_bootstrap(script_path)}"'

    def _module_command(self) -> str:
        if not self.config.entrypoint.module:
            raise RunnerError("Module entrypoint is not configured")
        return f'python -u "{self._write_module_bootstrap()}"'

    def _project_command(self) -> str:
        if not self.config.entrypoint.command:
            raise RunnerError("Project command entrypoint is not configured")
        return shlex.join([self.config.entrypoint.command, *self.config.entrypoint.args])

    def _launch_popen_kwargs(self) -> dict:
        return {
            "cwd": self.config.working_directory_path,
        }

    def _write_script_bootstrap(self, script_path) -> str:
        runtime_dir = get_runtime_data_dir(self.config.name)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        bootstrap_path = runtime_dir / "launcher-run.py"
        sys_paths = self._launch_sys_paths(script_path)
        argv = [str(script_path), *self.config.entrypoint.args]
        bootstrap_path.write_text(
            "\n".join(
                [
                    "# Generated by Launcher before starting the app.",
                    "import runpy",
                    "import sys",
                    "",
                    f"sys.path[:0] = {[str(path) for path in sys_paths]!r}",
                    f"sys.argv = {argv!r}",
                    f"runpy.run_path({str(script_path)!r}, run_name='__main__')",
                    "",
                ]
            )
        )
        return bootstrap_path.as_posix()

    def _write_module_bootstrap(self) -> str:
        runtime_dir = get_runtime_data_dir(self.config.name)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        bootstrap_path = runtime_dir / "launcher-run.py"
        module = self.config.entrypoint.module
        argv = [module, *self.config.entrypoint.args]
        sys_paths = self._launch_sys_paths(None)
        bootstrap_path.write_text(
            "\n".join(
                [
                    "# Generated by Launcher before starting the app.",
                    "import runpy",
                    "import sys",
                    "",
                    f"sys.path[:0] = {[str(path) for path in sys_paths]!r}",
                    f"sys.argv = {argv!r}",
                    f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)",
                    "",
                ]
            )
        )
        return bootstrap_path.as_posix()

    def _launch_sys_paths(self, script_path) -> list:
        paths = [*self.config.pythonpath_paths]
        if script_path is not None:
            paths.append(script_path.parent)
        unique_paths = []
        seen = set()
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique_paths.append(path)
        return unique_paths

    def ensure_still_running(self, grace_seconds: float = 1.0) -> None:
        """Raise if the launched application exits immediately."""
        if not self._process:
            raise RunnerError("Application process was not started")

        time.sleep(grace_seconds)
        exit_code = self._process.poll()
        if exit_code is None:
            return

        recent_output = self.recent_output()
        message = (
            f"Application exited immediately after launch with exit code {exit_code}.\n"
            f"Launcher started `{self.config.entrypoint_label}` from "
            f"{self.config.working_directory_path}.\n"
            "Run the same script from the configured environment to debug the app, "
            "or configure `init_message` if Launcher should wait for a startup signal."
        )
        if recent_output:
            message = f"{message}\nRecent application output:\n{recent_output}"
        raise RunnerError(message)

    def recent_output(self, max_lines: int = 20) -> str:
        """Return recent captured app output."""
        with self._lock:
            return "\n".join(self._output_lines[-max_lines:])

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

        if not self._process_logger:
            logger.warning("No process logger available, cannot wait for init message")
            return False

        timeout = self.config.init_timeout
        init_message = self.config.init_message

        def init_predicate(line: str) -> bool:
            return init_message in line

        while True:
            line = self._process_logger.wait_for_line(init_predicate, timeout=timeout)
            if line:
                logger.info(f"Init message received: {init_message}")
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
