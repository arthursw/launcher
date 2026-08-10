"""Script execution and initialization monitoring."""

import asyncio
import logging
from pathlib import Path
import threading
import time
from typing import Callable, Optional

from wetlands import (
    ManagedEnvironment,
    ManagedProcess,
    ManagedProcessResult,
    OutputEvent,
    OutputStream,
    ProcessError,
    ProcessEventLagError,
    ProcessLineTimeoutError,
)

from .config import AppConfig
from .environment import LauncherEnvironmentManager
from .paths import get_runtime_data_dir

logger = logging.getLogger(__name__)

# Type aliases
OutputCallback = Callable[[str], None]
InitTimeoutCallback = Callable[[], str]  # Returns 'wait', 'reinstall', or 'exit'
MANAGED_PROCESS_OUTPUT_LIMIT = 16 * 1024 * 1024


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
        env: ManagedEnvironment,
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
        self._process: Optional[ManagedProcess] = None
        self._output_lines: list[str] = []
        self._output_condition = threading.Condition()
        self._reader_thread: Optional[threading.Thread] = None

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
            result = self.env.run(
                ["python", str(install_path)],
                cwd=self.config.working_directory_path,
                output_limit=MANAGED_PROCESS_OUTPUT_LIMIT,
                check=False,
            )
            self._record_result_output(result)

            if result.returncode != 0:
                logger.error(f"Install script failed with return code {result.returncode}")
                return False

            logger.info("Install script completed successfully")
            return True
        except Exception as e:
            logger.error(f"Install script failed: {e}")
            return False

    def start(
        self,
        output_callback: Optional[OutputCallback] = None,
    ) -> ManagedProcess:
        """Start the configured entrypoint.

        Args:
            output_callback: Optional callback for stdout lines

        Returns:
            The Wetlands managed process
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

        output_path = self._application_output_path()
        self._process = self.env.spawn(
            command,
            cwd=working_directory,
            output_limit=MANAGED_PROCESS_OUTPUT_LIMIT,
        )
        self._reader_thread = threading.Thread(
            target=self._capture_output_events,
            args=(output_path, self._process, output_callback),
            name=f"launcher-output-{self.config.env_name}",
            daemon=True,
        )
        self._reader_thread.start()

        return self._process

    def _application_output_path(self) -> Path:
        runtime_dir = get_runtime_data_dir(self.config.name)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir / "launcher-app.log"

    def _capture_output_events(
        self,
        output_path: Path,
        process: ManagedProcess,
        output_callback: Optional[OutputCallback],
    ) -> None:
        try:
            asyncio.run(self._consume_output_events(output_path, process, output_callback))
        except ProcessEventLagError as e:
            logger.warning("Application output observer fell behind: %s", e)
        except Exception:
            logger.exception("Application output observer failed")
        with self._output_condition:
            self._output_condition.notify_all()

    async def _consume_output_events(
        self,
        output_path: Path,
        process: ManagedProcess,
        output_callback: Optional[OutputCallback],
    ) -> None:
        with output_path.open("w", encoding="utf-8", buffering=1) as output:
            async for event in process.events():
                line = self._display_output_event(event)
                output.write(line)
                if event.text.endswith(("\n", "\r")):
                    output.write("\n" if not line.endswith("\n") else "")
                with self._output_condition:
                    self._output_lines.append(line.rstrip("\r\n"))
                    self._output_condition.notify_all()
                if output_callback:
                    try:
                        output_callback(line.rstrip("\r\n"))
                    except Exception:
                        logger.exception("Application output callback failed")

    @staticmethod
    def _display_output_event(event: OutputEvent) -> str:
        prefix = "[stderr] " if event.stream is OutputStream.STDERR else ""
        return f"{prefix}{event.text}"

    def _record_result_output(self, result: ManagedProcessResult) -> None:
        lines = [*result.stdout.splitlines(), *(f"[stderr] {line}" for line in result.stderr.splitlines())]
        if lines:
            with self._output_condition:
                self._output_lines.extend(lines)
                self._output_condition.notify_all()

    def _script_command(self) -> list[str]:
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
        return ["python", "-u", self._write_script_bootstrap(script_path)]

    def _module_command(self) -> list[str]:
        if not self.config.entrypoint.module:
            raise RunnerError("Module entrypoint is not configured")
        return ["python", "-u", self._write_module_bootstrap()]

    def _project_command(self) -> list[str]:
        if not self.config.entrypoint.command:
            raise RunnerError("Project command entrypoint is not configured")
        return [self.config.entrypoint.command, *self.config.entrypoint.args]

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
        exit_code = self._process.returncode
        if exit_code is None:
            return

        try:
            self._process.wait(check=False)
        except ProcessError as e:
            raise RunnerError(f"Application process cleanup failed: {e}") from e

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
        with self._output_condition:
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

        if not self._process:
            logger.warning("Application process was not started, cannot wait for init message")
            return False

        timeout = self.config.init_timeout
        init_message = self.config.init_message

        while True:
            try:
                self._process.wait_for_line(
                    lambda event: init_message in event.text,
                    timeout=timeout,
                )
                logger.info(f"Init message received: {init_message}")
                return True
            except EOFError:
                try:
                    result = self._process.wait(check=False)
                except ProcessError as e:
                    raise InitTimeoutError(
                        f"Application process failed before initialization completed: {e}"
                    ) from e
                logger.error(f"Process exited with code {result.returncode} before init message")
                raise InitTimeoutError(
                    f"Process exited (code {result.returncode}) before init message was received"
                )
            except ProcessLineTimeoutError:
                pass
            except ProcessError as e:
                raise InitTimeoutError(f"Application process failed while waiting for initialization: {e}") from e

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
        if not self._process:
            return

        logger.info("Stopping process")
        try:
            self._process.close()
        except ProcessError as e:
            raise RunnerError(f"Failed to clean up application process: {e}") from e

        self._process = None
        self._join_output_reader()

    def wait_for_exit(self) -> int:
        """Wait for the managed application and its descendants to exit cleanly."""
        if not self._process:
            raise RunnerError("Application process was not started")
        try:
            result = self._process.wait(check=False)
            self._process.close()
        except ProcessError as e:
            raise RunnerError(f"Application process supervision failed: {e}") from e

        self._process = None
        self._join_output_reader()
        return result.returncode

    def _join_output_reader(self) -> None:
        if not self._reader_thread:
            return
        self._reader_thread.join(timeout=1)
        if self._reader_thread.is_alive():
            logger.warning("Application output observer did not stop promptly")
        self._reader_thread = None

    @property
    def is_running(self) -> bool:
        """Check if the process is still running."""
        return self._process is not None and self._process.running

    @property
    def return_code(self) -> Optional[int]:
        """Get the process return code, or None if still running."""
        if self._process:
            return self._process.returncode
        return None

    @property
    def output_lines(self) -> list[str]:
        """Get all captured output lines."""
        with self._output_condition:
            return self._output_lines.copy()
