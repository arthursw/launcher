"""Core launcher functionality for auto-updating and running applications."""

from math import e
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import requests
import yaml
from wetlands.environment_manager import EnvironmentManager, Environment

from repository_parser import parse_repository_url, merge_endpoints


class Launcher:
    """Main launcher class for managing application lifecycle."""

    def __init__(self, config_path: str, path_override: Optional[str] = None):
        """Initialize launcher with application configuration.

        Args:
            config_path: Path to application.yml configuration file
            path_override: Optional override for the path attribute from config

        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If config file is invalid YAML
            ValueError: If neither repository nor explicit endpoints are provided
        """
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        self.config = self.load_config()

        # Override path if provided
        if path_override:
            self.config["path"] = path_override

        # Resolve API endpoints (from repository or explicit config)
        self._resolve_endpoints()

        self.environment_manager = None

    def load_config(self) -> dict:
        """Load and parse application.yml configuration file.

        Returns:
            Configuration dictionary

        Raises:
            yaml.YAMLError: If YAML is invalid
        """
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f)

    def save_config(self) -> None:
        """Save configuration back to application.yml file."""
        with open(self.config_path, "w") as f:
            yaml.safe_dump(self.config, f, default_flow_style=False)

    def _resolve_endpoints(self) -> None:
        """Resolve API endpoints from repository or explicit config values.

        If repository is provided, infers endpoints from it.
        Explicit api, tags_endpoint, and archive_endpoint take priority.

        Raises:
            ValueError: If neither repository nor explicit endpoints are provided
        """
        has_explicit_api = "api" in self.config
        has_explicit_tags = "tags_endpoint" in self.config
        has_explicit_archive = "archive_endpoint" in self.config
        has_repository = "repository" in self.config

        # If all three endpoints are explicitly provided, no need to infer
        if has_explicit_api and has_explicit_tags and has_explicit_archive:
            return

        # If repository is provided, infer endpoints
        if has_repository:
            inferred = parse_repository_url(self.config["repository"])
            explicit = {
                "api": self.config.get("api"),
                "tags_endpoint": self.config.get("tags_endpoint"),
                "archive_endpoint": self.config.get("archive_endpoint"),
            }
            merged = merge_endpoints(inferred, explicit)
            self.config["api"] = merged["api"]
            self.config["tags_endpoint"] = merged["tags_endpoint"]
            self.config["archive_endpoint"] = merged["archive_endpoint"]
            return

        # If no repository but we have all three endpoints, that's fine
        if has_explicit_api and has_explicit_tags and has_explicit_archive:
            return

        # Otherwise, we need at least a repository or all three endpoints
        raise ValueError(
            "Configuration must include either 'repository' or all three of "
            "'api', 'tags_endpoint', and 'archive_endpoint'"
        )

    def get_current_version(self) -> str:
        """Get current version to run.

        If auto_update is True, fetches latest tag from API.
        Otherwise, returns version from config.

        Returns:
            Version string in format "appname-tagname"
        """
        if not self.config.get("auto_update", False):
            return self.config["version"]

        try:
            api_url = self.config["api"]
            tags_endpoint = self.config["tags_endpoint"]

            # Fetch tags from API
            full_url = api_url.rstrip("/") + tags_endpoint
            response = requests.get(full_url, timeout=10)
            response.raise_for_status()

            tags = response.json()
            if not tags:
                return self.config["version"]

            # Get latest tag (first one in the list)
            latest_tag = tags[0]["name"]
            return f"{latest_tag}"

        except Exception as e:
            # On any error, fall back to config version
            print(f"Failed to fetch latest version: {e}")
            return self.config["version"]

    def sources_exist(self, version: str) -> bool:
        """Check if sources for a given version exist locally.

        Args:
            version: Version string in format "appname-tagname"

        Returns:
            True if sources directory exists
        """
        path = Path(self.config["path"]) / version
        return path.exists() and path.is_dir()

    def download_sources(self, version: str) -> None:
        """Download and extract sources for a given version.

        Args:
            version: Version string in format "appname-tagname"

        Raises:
            Exception: On download or extraction failure
        """
        api_url = self.config["api"]
        archive_endpoint = self.config["archive_endpoint"]

        # Extract tag name from version (remove project prefix)
        tag_name = version.split("-", 1)[1]

        # Build download URL
        archive_url = api_url.rstrip("/") + archive_endpoint.format(ref=tag_name)

        print(f"Downloading sources from {archive_url}")

        # Download archive
        response = requests.get(archive_url, timeout=30)
        response.raise_for_status()

        # Extract to temporary directory first
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "archive.zip"
            zip_path.write_bytes(response.content)

            # Extract and handle directory structure
            extract_dir = Path(tmpdir) / "extracted"
            extract_dir.mkdir()

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            # Find the extracted content (often in a subdirectory)
            extracted_contents = list(extract_dir.iterdir())
            if len(extracted_contents) == 1 and extracted_contents[0].is_dir():
                source_dir = extracted_contents[0]
            else:
                source_dir = extract_dir

            # Move to final location
            dest_path = Path(self.config["path"]) / version
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if dest_path.exists():
                shutil.rmtree(dest_path)
            shutil.move(str(source_dir), str(dest_path))

        print(f"Sources extracted to {dest_path}")

    @staticmethod
    def _sanitize_env_name(name: str) -> str:
        """Convert application name to valid conda environment name.

        Removes special characters and converts to lowercase.

        Args:
            name: Application name

        Returns:
            Sanitized name suitable for conda environment
        """
        # Remove special characters, keep alphanumeric, underscore, hyphen
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", name)
        return sanitized.lower()

    def setup_environment(self, version: str) -> Environment:
        """Set up Python environment for the application.

        Creates a conda environment and installs dependencies from
        the configuration file (e.g., pyproject.toml).

        Args:
            version: Version string in format "appname-tagname"
        """
        source_dir = Path(self.config["path"]) / version
        config_file = self.config["configuration"]
        config_path = source_dir / config_file

        if not config_path.exists():
            raise Exception(f"Configuration file {config_file} not found")

        # Create environment name from application name
        env_name = self._sanitize_env_name(self.config["name"])

        if self.environment_manager is None:
            self.environment_manager = EnvironmentManager()

        print(f"Setting up environment: {env_name}")

        # Create environment with dependencies from config file
        env_path = self.environment_manager.settingsManager.getEnvironmentPathFromName(env_name)
        env_exists = self.environment_manager.environmentExists(env_path)
        env = self.environment_manager.createFromConfig(env_name, str(config_path))
        # Run install script if defined
        install_script = self.config.get("install_script")
        if not env_exists and install_script:
            env.executeCommands([f"bash {install_script}"])
        return env

    def run_app(self, env: Environment) -> None:
        """Run the main application script within the given environment.

        Args:
            env: Environment object to run the application in
        """
        main_script = self.config["main"]
        print(f"Running application: {main_script}")
        env.executeCommands([f"python {main_script}"])

    def run(self) -> None:
        """Main launcher orchestration method.

        This method:
        1. Determines current version (from config or latest tag)
        2. Downloads sources if necessary
        3. Sets up environment and runs the install script if necessary
        4. Runs the application
        """
        version = self.get_current_version()
        print(f"Current version: {version}")

        # Update config with current version
        self.config["version"] = version
        self.save_config()

        # Download if necessary
        if not self.sources_exist(version):
            print(f"Sources not found for {version}, downloading...")
            self.download_sources(version)

        # Setup environment
        env = self.setup_environment(version)

        # Run application
        self.run_app(env)
