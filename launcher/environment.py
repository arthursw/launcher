"""Environment management wrapper around Wetlands library."""

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

# Import wetlands - it's symlinked at the project root
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "wetlands" / "src"))

from wetlands.environment_manager import EnvironmentManager
from wetlands.environment import Environment

if TYPE_CHECKING:
    from .config import AppConfig

logger = logging.getLogger(__name__)

# Type alias for output callback: (line: str) -> None
OutputCallback = Callable[[str], None]


class EnvironmentError(Exception):
    """Exception for environment-related errors."""
    pass


class LauncherEnvironmentManager:
    """Wrapper around Wetlands EnvironmentManager for the launcher application."""

    def __init__(
        self,
        wetlands_path: Optional[Path] = None,
        log_file_path: Optional[Path] = None,
    ) -> None:
        """Initialize the environment manager.

        Args:
            wetlands_path: Path where Wetlands stores its data (pixi installation, etc.)
                          Defaults to ~/.launcher/wetlands
            log_file_path: Path to the log file. Defaults to wetlands_path/wetlands.log
        """
        if wetlands_path is None:
            wetlands_path = Path.home() / ".launcher" / "wetlands"

        wetlands_path.mkdir(parents=True, exist_ok=True)

        if log_file_path is None:
            log_file_path = wetlands_path / "wetlands.log"

        self._manager = EnvironmentManager(
            wetlands_instance_path=wetlands_path,
            log_file_path=log_file_path,
        )

        logger.info(f"EnvironmentManager initialized at {wetlands_path}")

    def environment_exists(self, env_name: str) -> bool:
        """Check if an environment with the given name exists.

        Args:
            env_name: The sanitized environment name

        Returns:
            True if the environment exists
        """
        env_path = self._manager.settings_manager.get_environment_path_from_name(env_name)
        return self._manager.environment_exists(env_path)

    def get_or_create_environment(
        self,
        config: "AppConfig",
    ) -> Environment:
        """Get an existing environment or create a new one.

        Args:
            config: Application configuration

        Returns:
            The Wetlands Environment instance
        """
        env_name = config.env_name
        config_file_path = config.config_file_path

        if config_file_path and config_file_path.exists():
            logger.info(f"Creating environment '{env_name}' from config: {config_file_path}")
            return self._manager.create_from_config(
                name=env_name,
                config_path=config_file_path,
            )
        else:
            logger.info(f"Creating environment '{env_name}' with no dependencies")
            return self._manager.create(name=env_name)

    def delete_environment(self, env_name: str) -> bool:
        """Delete an environment.

        Args:
            env_name: The sanitized environment name

        Returns:
            True if the environment was deleted, False if it didn't exist
        """
        env_path = self._manager.settings_manager.get_environment_path_from_name(env_name)

        if not self._manager.environment_exists(env_path):
            logger.warning(f"Environment '{env_name}' does not exist")
            return False

        # Load the environment to get access to delete method
        try:
            env = self._manager.load(env_name, env_path)
            env.delete()
            logger.info(f"Environment '{env_name}' deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete environment '{env_name}': {e}")
            raise EnvironmentError(f"Failed to delete environment: {e}") from e

    def execute_commands(
        self,
        env: Environment,
        commands: list[str],
        wait: bool = True,
        output_callback: Optional[OutputCallback] = None,
    ) -> subprocess.Popen:
        """Execute commands in an environment.

        Args:
            env: The Wetlands Environment
            commands: List of commands to execute
            wait: Whether to wait for completion
            output_callback: Optional callback for stdout lines

        Returns:
            The subprocess.Popen instance
        """
        # Convert list to Commands format expected by Wetlands
        commands_dict = {"all": commands}

        process = env.execute_commands(
            commands=commands_dict,
            wait=wait,
        )

        if output_callback and process.stdout:
            # Read output and call callback for each line
            for line in process.stdout:
                line = line.strip()
                if line:
                    output_callback(line)

        return process

    def run_script(
        self,
        env: Environment,
        script_path: Path,
        output_callback: Optional[OutputCallback] = None,
    ) -> subprocess.Popen:
        """Run a Python script in the environment.

        Args:
            env: The Wetlands Environment
            script_path: Path to the Python script
            output_callback: Optional callback for stdout lines

        Returns:
            The subprocess.Popen instance
        """
        commands = [f'python "{script_path}"']
        return self.execute_commands(
            env,
            commands,
            wait=False,
            output_callback=output_callback,
        )

    def set_proxies(self, http_proxy: Optional[str], https_proxy: Optional[str]) -> None:
        """Set proxy settings for the environment manager.

        Args:
            http_proxy: HTTP proxy URL
            https_proxy: HTTPS proxy URL
        """
        proxies = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy

        if proxies:
            self._manager.set_proxies(proxies)
            logger.info(f"Proxies set: {proxies}")

    def exit(self) -> None:
        """Clean up and exit all environments."""
        self._manager.exit()
