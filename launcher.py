# launcher.py
import os
import sys
import platform
import yaml
import requests
import zipfile
import tarfile
import io
import shutil
import logging
import time
import re
import subprocess
import toml
import threading
from pathlib import Path
from urllib.parse import urljoin
from wetlands._internal.dependency_manager import Dependencies
from wetlands.environment_manager import EnvironmentManager
from textual.app import App
from typing import cast

# Import GUI components if available
try:
    from gui import ProxyDialog, LauncherGUI, log_queue, queue_handler # Import handler too
    gui_available = True
except ImportError:
    gui_available = False
    ProxyDialog = None # type: ignore
    LauncherGUI = None # type: ignore
    log_queue = None # type: ignore
    queue_handler = None # type: ignore


# --- Configuration ---
CONFIG_FILE = "application.yml"
MICROMAMBA_DIR = Path("micromamba") # Relative to launcher location
DEFAULT_TIMEOUT = 3

# Basic logging setup (console initially, GUI handler added later if needed)
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])


# --- Helper Functions ---

def get_script_dir() -> Path:
    """Gets the directory containing the script or frozen executable."""
    if getattr(sys, 'frozen', False):
        # PyInstaller executable
        return Path(sys.executable).parent
    else:
        # Regular Python script
        return Path(__file__).parent

def sanitize_env_name(name: str) -> str:
    """Removes special characters to create a valid Conda environment name."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)

def find_conda_config_files():
    """Generates potential paths for conda/mamba config files."""
    potential_paths = []
    system = platform.system()
    home = Path.home()
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    conda_root = Path(os.environ.get("CONDA_ROOT", ""))
    mamba_root = Path(os.environ.get("MAMBA_ROOT_PREFIX", MICROMAMBA_DIR.resolve())) # Default to our micromamba dir
    conda_prefix = Path(os.environ.get("CONDA_PREFIX", ""))

    if system == 'Windows':
        potential_paths.extend([
            Path("C:/ProgramData/conda/.condarc"),
            Path("C:/ProgramData/conda/condarc"),
            # Path("C:/ProgramData/conda/condarc.d"), # Needs directory handling
            Path("C:/ProgramData/conda/.mambarc"),
        ])
    else:
        potential_paths.extend([
            Path("/etc/conda/.condarc"),
            Path("/etc/conda/condarc"),
            # Path("/etc/conda/condarc.d/"),
            Path("/etc/conda/.mambarc"),
            Path("/var/lib/conda/.condarc"),
            Path("/var/lib/conda/condarc"),
            # Path("/var/lib/conda/condarc.d/"),
            Path("/var/lib/conda/.mambarc"),
        ])

    if conda_root:
        potential_paths.extend([
            conda_root / ".condarc",
            conda_root / "condarc",
            # conda_root / "condarc.d/",
        ])
    if mamba_root:
        potential_paths.extend([
            mamba_root / ".condarc",
            mamba_root / "condarc",
            # mamba_root / "condarc.d/",
            mamba_root / ".mambarc",
        ])

    potential_paths.extend([
        xdg_config_home / "conda/.condarc",
        xdg_config_home / "conda/condarc",
        # xdg_config_home / "conda/condarc.d/",
        home / ".config/conda/.condarc",
        home / ".config/conda/condarc",
        # home / ".config/conda/condarc.d/",
        home / ".conda/.condarc",
        home / ".conda/condarc",
        # home / ".conda/condarc.d/",
        home / ".condarc",
        home / ".mambarc",
    ])

    if conda_prefix:
         potential_paths.extend([
            conda_prefix / ".condarc",
            conda_prefix / "condarc",
            # conda_prefix / "condarc.d/",
        ])

    # Environment variables pointing directly to files
    if os.environ.get("CONDARC"):
        potential_paths.append(Path(os.environ["CONDARC"]))
    if os.environ.get("MAMBARC"):
        potential_paths.append(Path(os.environ["MAMBARC"]))

    # Configs relative to our micromamba install
    script_dir = get_script_dir()
    mamba_local_dir = script_dir / MICROMAMBA_DIR
    potential_paths.extend([
        mamba_local_dir / ".condarc",
        mamba_local_dir / "condarc",
        # mamba_local_dir / "condarc.d/", # Needs dir handling
        mamba_local_dir / ".mambarc",
    ])

    # Filter out duplicates and non-existent files/dirs we can't handle yet
    unique_files = {p.resolve() for p in potential_paths if p.is_file()}
    # TODO: Add handling for condarc.d directories if needed

    logging.debug(f"Potential config files considered: {[str(p) for p in unique_files]}")
    return list(unique_files)


def parse_conda_configs(files: list[Path]) -> dict | None:
    """Parses conda config files to find proxy_servers."""
    proxies = None
    for config_path in files:
        try:
            logging.debug(f"Attempting to read config: {config_path}")
            if config_path.exists() and config_path.is_file():
                with open(config_path, 'r') as f:
                    config_data = yaml.safe_load(f)
                    if isinstance(config_data, dict) and "proxy_servers" in config_data:
                        found_proxies = config_data["proxy_servers"]
                        if isinstance(found_proxies, dict) and ('http' in found_proxies or 'https' in found_proxies):
                            logging.info(f"Found proxy settings in {config_path}")
                            # Merge, potentially overwriting with later files? Conda's precedence is complex.
                            # Let's just take the first one found for simplicity here.
                            if proxies is None:
                                proxies = found_proxies
                            # return found_proxies # Or take the first one found
        except Exception as e:
            logging.warning(f"Could not read or parse {config_path}: {e}")
    if proxies:
        logging.info(f"Using proxies found in system config: {proxies}")
    else:
        logging.debug("No proxy_servers found in system config files.")
    return proxies


def update_mambarc(proxy_settings: dict | None):
    """Updates the local .mambarc file with proxy settings."""
    script_dir = get_script_dir()
    mambarc_path = script_dir / MICROMAMBA_DIR / ".mambarc"
    mambarc_path.parent.mkdir(parents=True, exist_ok=True) # Ensure micromamba dir exists

    config_data = {}
    # Read existing config if it exists
    if mambarc_path.exists():
        try:
            with open(mambarc_path, 'r') as f:
                existing_config = yaml.safe_load(f)
                if isinstance(existing_config, dict):
                    config_data = existing_config
        except Exception as e:
            logging.warning(f"Could not read existing {mambarc_path}, overwriting. Error: {e}")

    # Update proxy settings
    if proxy_settings:
        config_data["proxy_servers"] = proxy_settings
    elif "proxy_servers" in config_data:
        # Remove proxy settings if None is provided
        del config_data["proxy_servers"]

    # Write back the updated config
    try:
        with open(mambarc_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False)
        logging.info(f"Updated {mambarc_path} with proxy settings: {proxy_settings}")
    except Exception as e:
        logging.error(f"Failed to write updated {mambarc_path}: {e}")

# --- Blocking Proxy Input Function ---
def request_proxy_details_blocking() -> dict | None:
    """
    Runs a minimal Textual app IN THE MAIN THREAD to get proxy details.
    Blocks until the user provides input or cancels.
    """
    if not gui_available or not ProxyDialog:
        logging.error("GUI components not available to request proxy details.")
        return None

    class ProxyApp(App[dict | None]):
        """Minimal app to host the ProxyDialog."""
        def on_mount(self) -> None:
            if not ProxyDialog: return
            self.push_screen(ProxyDialog(), self.exit) # Exit app when dialog returns

    logging.info("Launching GUI to request proxy details...")
    proxy_app = ProxyApp()
    result = proxy_app.run() # This BLOCKS and runs in the main thread
    logging.info(f"Proxy GUI finished. Received: {result}")
    return result


# --- Main Launcher Class ---

class AppLauncher:
    def __init__(self):
        self.script_dir = get_script_dir()
        self.config_path = self.script_dir / CONFIG_FILE
        self.config = self._load_config()
        self.session = requests.Session()
        self.env_manager: EnvironmentManager | None = None
        self.target_version: str | None = None
        self.source_dir: Path | None = None
        self.env_name: str | None = None
        self.app_env = None # Stores the wetlands Environment object
        self.proxy_settings: dict | None = None # Holds currently active proxy settings
        self.log_capture_handler: logging.handlers.MemoryHandler | None = None # For capturing logs for error GUI

    def _load_config(self) -> dict:
        """Loads configuration from application.yml."""
        logging.info(f"Loading configuration from {self.config_path}")
        if not self.config_path.exists():
            logging.critical(f"Configuration file '{CONFIG_FILE}' not found!")
            raise FileNotFoundError(f"Configuration file '{CONFIG_FILE}' not found!")
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
                # Basic validation
                required_keys = ['name', 'api', 'tags_endpoint', 'archive_endpoint', 'main', 'path']
                for key in required_keys:
                    if key not in config:
                        raise ValueError(f"Missing required key '{key}' in {CONFIG_FILE}")
                # Set defaults if missing
                config.setdefault('version', None)
                config.setdefault('auto_update', True)
                config.setdefault('project', config['name']) # Default project name/id to app name
                config.setdefault('configuration', 'pyproject.toml') # Default config file
                config.setdefault('timeout', DEFAULT_TIMEOUT)
                config.setdefault('proxy_servers', None)
                return config
        except Exception as e:
            logging.critical(f"Error loading configuration: {e}")
            raise

    def _save_config(self):
        """Saves the current configuration back to application.yml."""
        logging.info(f"Saving updated configuration to {self.config_path}")
        try:
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config, f, sort_keys=False, default_flow_style=False)
        except Exception as e:
            logging.error(f"Error saving configuration: {e}")

    def _configure_proxies(self, proxies: dict | None):
        """Configures requests session and potentially mamba with proxies."""
        self.proxy_settings = proxies
        if proxies:
            logging.info(f"Using proxies: {proxies}")
            self.session.proxies = proxies
            # Also update micromamba's config file
            update_mambarc(proxies)
        else:
            logging.info("No proxies configured.")
            self.session.proxies = {}
            # Remove from mambarc if they existed
            update_mambarc(None)

        # Set environment variables for subprocesses (like micromamba calls within wetlands)
        # Wetlands might respect HTTP_PROXY/HTTPS_PROXY
        if proxies:
            if 'http' in proxies:
                os.environ['HTTP_PROXY'] = proxies['http']
            if 'https' in proxies:
                os.environ['HTTPS_PROXY'] = proxies['https']
        else:
            if 'HTTP_PROXY' in os.environ: del os.environ['HTTP_PROXY']
            if 'HTTPS_PROXY' in os.environ: del os.environ['HTTPS_PROXY']


    def _handle_network_config(self):
        """Checks system, config file, and user input for proxy settings."""
        # 1. Check application.yml first
        config_proxies = self.config.get('proxy_servers')
        if config_proxies and isinstance(config_proxies, dict):
             logging.info("Using proxy settings from application.yml")
             self._configure_proxies(config_proxies)
             return

        # 2. Check system/conda config files
        system_config_files = find_conda_config_files()
        system_proxies = parse_conda_configs(system_config_files)
        if system_proxies:
            logging.info("Using proxy settings found in system conda/mamba config files.")
            self._configure_proxies(system_proxies)
            # Optionally save these discovered proxies to application.yml?
            # self.config['proxy_servers'] = system_proxies
            # self._save_config()
            return
        
        # 3. If no proxies found, attempt a test connection (if auto-update is on)
        if self.config.get('auto_update', True):
            logging.info("No proxy settings found in configs. Testing connection...")
            try:
                # Use a non-proxied session for the test
                test_url = self.config['api']
                requests.get(test_url, timeout=5)
                logging.info("Direct connection successful. No proxy needed.")
                self._configure_proxies(None)
                return
            except requests.exceptions.RequestException as e:
                logging.warning(f"Direct connection failed: {e}. Proxy might be required.")
                # Proceed to ask user if GUI is available

        # 4. Ask user via *blocking* GUI if connection failed/untested and GUI is available
        if gui_available:
            logging.warning("Attempting to prompt user for proxy settings via blocking GUI.")
            user_proxies = request_proxy_details_blocking() # Calls the new blocking function
            if user_proxies:
                logging.info(f"Received proxy settings from user: {user_proxies}")
                self.config['proxy_servers'] = user_proxies # Save to config dict
                self._save_config() # Persist to file
                self._configure_proxies(user_proxies) # Apply settings
            else:
                logging.warning("User did not provide proxy settings or cancelled. Proceeding without proxies.")
                self._configure_proxies(None)
        else:
            # Case where connection failed/untested and GUI is NOT available
            logging.warning("No proxies configured, connection failed/untested, and GUI is not available. Proceeding without proxies.")
            self._configure_proxies(None)



    def _get_latest_version_tag(self) -> tuple[str, str] | None:
        """Fetches the latest tag name and its ref (commit sha or tag name) from the API."""
        api_base = self.config['api']
        tags_endpoint = self.config['tags_endpoint'].lstrip('/')
        url = urljoin(api_base, tags_endpoint)
        # Handle potential project ID replacement for GitLab
        url = url.replace('{projectId}', str(self.config.get('project', '')))

        logging.info(f"Fetching latest tag from {url}")
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            tags_data = response.json()

            if not tags_data:
                logging.warning("No tags found.")
                return None

            # --- Tag structure depends on GitHub vs GitLab ---
            # GitHub: List of objects like {"ref": "refs/tags/v0.1.0", "object": {"sha": "...", "type": "tag"}}
            #         or directly {"name": "v0.1.0", "commit": {"sha": "..." }} (tags endpoint)
            # GitLab: List of objects like {"name": "v0.1.0", "commit": {"id": "..."}}

            # Simplistic approach: Assume the last tag in the list is the latest.
            # A robust solution would parse versions (e.g., using 'packaging' library)
            latest_tag_info = tags_data[-1]

            if isinstance(latest_tag_info, dict):
                tag_name: str = cast(str, latest_tag_info.get('name')) # Common field
                ref = tag_name # Default ref is the tag name itself

                # Github specific for /git/tags endpoint
                if 'ref' in latest_tag_info and latest_tag_info['ref'].startswith('refs/tags/'):
                    tag_name = latest_tag_info['ref'].split('/')[-1]
                    ref = tag_name # Use tag name for zipball endpoint

                if tag_name:
                    logging.info(f"Latest tag found: {tag_name}")
                    return tag_name, ref
                else:
                    logging.warning(f"Could not determine tag name from latest entry: {latest_tag_info}")
                    return None
            else:
                 logging.warning(f"Unexpected tag data format: {latest_tag_info}")
                 return None

        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch tags: {e}")
            # Reraise or handle connection/proxy issues more gracefully here
            raise NetworkError(f"Failed to fetch tags: {e}") from e
        except Exception as e:
            logging.error(f"Error processing tags data: {e}")
            return None


    def _determine_target_version(self):
        """Determines the version to install/run."""
        if self.config.get('auto_update', True):
            try:
                tag_info = self._get_latest_version_tag()
                if tag_info:
                    tag_name, _ = tag_info
                    self.target_version = f"{self.config['name']}-{tag_name}"
                    logging.info(f"Auto-update enabled. Target version set to latest: {self.target_version}")
                else:
                    logging.warning("Could not fetch latest tag. Falling back to pinned version (if any).")
                    self.target_version = self.config.get('version')
            except NetworkError:
                 logging.warning("Network error during tag fetch. Falling back to pinned version (if any).")
                 self.target_version = self.config.get('version')

        else:
            self.target_version = self.config.get('version')
            logging.info(f"Auto-update disabled. Target version pinned to: {self.target_version}")

        if not self.target_version:
            raise ValueError("Could not determine target version (auto-update failed and no version pinned).")

        # Update config immediately if auto-update found a version different from pinned one
        # Or if no version was pinned before
        if self.config.get('version') != self.target_version:
             self.config['version'] = self.target_version
             self._save_config() # Save the determined version


    def _get_source_dir(self) -> Path:
         """Calculates the expected source directory path."""
         base_path = Path(self.config['path']).expanduser()
         # Ensure base_path exists
         base_path.mkdir(parents=True, exist_ok=True)
         if not self.target_version:
             raise ValueError("Could not determine source directory because target version is None.")
         return base_path / self.target_version


    def _check_sources_exist(self) -> bool:
        """Checks if the source directory for the target version exists."""
        self.source_dir = self._get_source_dir()
        logging.info(f"Checking for application sources at: {self.source_dir}")
        return self.source_dir.is_dir()


    def _download_and_extract_sources(self):
        """Downloads and extracts the application sources."""
        if not self.target_version:
             raise RuntimeError("Target version not determined before download attempt.")

        # Extract the tag/ref part from the target_version (e.g., "appname-v1.0" -> "v1.0")
        version_parts = self.target_version.split(f"{self.config['name']}-", 1)
        if len(version_parts) != 2 or not version_parts[1]:
             raise ValueError(f"Cannot extract tag/ref from target version: {self.target_version}")
        tag_or_ref = version_parts[1]

        api_base = self.config['api']
        archive_endpoint = self.config['archive_endpoint'].lstrip('/')
        # Replace placeholders like {ref}, {projectId}, {owner}, {repo} etc.
        # We assume {ref} is standard. Others might need more config/logic.
        archive_endpoint = archive_endpoint.replace('{ref}', tag_or_ref)
        archive_endpoint = archive_endpoint.replace('{projectId}', str(self.config.get('project', '')))
        # Add specific replacements if needed based on common patterns
        if '/repos/' in archive_endpoint: # Likely GitHub structure
             # Try to guess owner/repo from tags_endpoint if not explicitly configured
             # Example: /repos/owner/exampleapp/git/tags -> owner, exampleapp
             match = re.search(r'/repos/([^/]+)/([^/]+)/', self.config['tags_endpoint'])
             if match:
                  owner, repo = match.groups()
                  archive_endpoint = archive_endpoint.replace('{owner}', owner)
                  archive_endpoint = archive_endpoint.replace('{repo}', repo)


        url = urljoin(api_base, archive_endpoint)

        logging.info(f"Downloading sources for {self.target_version} from {url}")

        temp_extract_dir = None

        try:
            response = self.session.get(url, stream=True, timeout=300) # Long timeout for download
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '').lower()
            is_zip = 'zip' in content_type or url.endswith('.zip')
            is_tar = 'tar' in content_type or '.tar' in url # tar, tar.gz, tar.bz2

            if not is_zip and not is_tar:
                logging.warning(f"Unknown content type '{content_type}' for archive. Assuming zip.")
                is_zip = True # Default guess

            archive_data = io.BytesIO(response.content) # Load into memory (careful with huge repos)
            # TODO: Stream directly to disk/extraction for large archives if memory becomes an issue

            # --- Extraction Logic ---
            self.source_dir = self._get_source_dir()
            if self.source_dir.exists():
                 logging.warning(f"Source directory {self.source_dir} already exists. Removing before extraction.")
                 shutil.rmtree(self.source_dir)

            # Create a temporary directory for extraction to handle archives
            # that might contain a single top-level folder.
            temp_extract_dir = self.source_dir.parent / f"{self.target_version}_temp_extract"
            if temp_extract_dir.exists():
                 shutil.rmtree(temp_extract_dir)
            temp_extract_dir.mkdir(parents=True)

            logging.info(f"Extracting archive to temporary location: {temp_extract_dir}")
            if is_zip:
                with zipfile.ZipFile(archive_data, 'r') as zip_ref:
                    zip_ref.extractall(temp_extract_dir)
            elif is_tar:
                # Determine compression (gz, bz2, or none)
                mode = "r:*" # Auto-detect compression
                if url.endswith(".tar"): mode = "r:"
                elif url.endswith(".tar.gz") or url.endswith(".tgz"): mode = "r:gz"
                elif url.endswith(".tar.bz2") or url.endswith(".tbz2"): mode = "r:bz2"
                with tarfile.open(fileobj=archive_data, mode=mode) as tar_ref:
                    tar_ref.extractall(path=temp_extract_dir) # Requires Python 3.8+ security features potentially

            extracted_items = list(temp_extract_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                content_dir = extracted_items[0]
                logging.info(f"Archive contained single directory '{content_dir.name}'. Moving its contents.")
                self.source_dir.mkdir(parents=True, exist_ok=True)
                for item in content_dir.iterdir():
                     source_item = content_dir / item.name
                     dest_item = self.source_dir / item.name
                     logging.debug(f"Moving {source_item} to {dest_item}")
                     shutil.move(str(source_item), str(dest_item)) # Move into final dest
                content_dir.rmdir()
                temp_extract_dir.rmdir()
            else:
                logging.info("Archive extracted directly. Renaming temp directory.")
                temp_extract_dir.rename(self.source_dir)

            logging.info(f"Sources successfully downloaded and extracted to {self.source_dir}")

        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to download sources: {e}")
            if self.source_dir and self.source_dir.exists(): shutil.rmtree(self.source_dir) # Clean up partial extraction
            if temp_extract_dir and temp_extract_dir.exists(): shutil.rmtree(temp_extract_dir)
            raise NetworkError(f"Failed to download sources: {e}") from e
        except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as e:
             logging.error(f"Failed to extract archive: {e}")
             if self.source_dir and self.source_dir.exists(): shutil.rmtree(self.source_dir) # Clean up partial extraction
             if temp_extract_dir and temp_extract_dir.exists(): shutil.rmtree(temp_extract_dir)
             raise RuntimeError(f"Failed to extract archive: {e}") from e
        except Exception as e:
            logging.error(f"An unexpected error occurred during download/extraction: {e}")
            if self.source_dir and self.source_dir.exists(): shutil.rmtree(self.source_dir) # Clean up
            if temp_extract_dir and temp_extract_dir.exists(): shutil.rmtree(temp_extract_dir)
            raise


    def _parse_dependencies(self) -> Dependencies:
        """Parses dependencies from the configured file (e.g., pyproject.toml)."""
        if not self.source_dir:
            raise RuntimeError("Source directory not set before parsing dependencies.")

        config_filename = self.config.get('configuration', 'pyproject.toml')
        config_filepath = self.source_dir / config_filename
        dependencies: Dependencies = {"pip": [], "conda": []} # Format expected by wetlands

        logging.info(f"Parsing dependencies from {config_filepath}")

        if not config_filepath.exists():
            logging.warning(f"Dependency configuration file '{config_filename}' not found in sources. No dependencies will be installed.")
            return dependencies

        try:
            if config_filename == 'pyproject.toml':
                parsed_toml = toml.load(config_filepath)
                # PEP 621 standard dependencies
                pip_deps = parsed_toml.get('project', {}).get('dependencies')
                if pip_deps and isinstance(pip_deps, list):
                    logging.info(f"Found {len(pip_deps)} pip dependencies in [project.dependencies]")
                    dependencies["pip"].extend(pip_deps)
                else:
                    # Fallback check for Poetry (common alternative)
                    poetry_deps = parsed_toml.get('tool', {}).get('poetry', {}).get('dependencies', {})
                    if isinstance(poetry_deps, dict):
                        # Poetry format: { "package": "version", "python": "..." }
                        # Convert to pip format: ["package==version", ...]
                        # Exclude the python version key
                        pip_deps_poetry = [f"{pkg}{ver}" for pkg, ver in poetry_deps.items() if pkg.lower() != 'python']
                        if pip_deps_poetry:
                             logging.info(f"Found {len(pip_deps_poetry)} pip dependencies in [tool.poetry.dependencies]")
                             dependencies["pip"].extend(pip_deps_poetry)

                # Look for conda dependencies (non-standard, maybe under [tool.conda]?)
                # Example: [tool.launcher.conda_dependencies]
                conda_deps = parsed_toml.get('tool', {}).get(self.config['name'], {}).get('conda_dependencies') # Or a generic name?
                if conda_deps and isinstance(conda_deps, list):
                     logging.info(f"Found {len(conda_deps)} conda dependencies")
                     dependencies["conda"].extend(conda_deps)

            elif config_filename == 'requirements.txt':
                 with open(config_filepath, 'r') as f:
                      pip_deps = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                      if pip_deps:
                          logging.info(f"Found {len(pip_deps)} pip dependencies in requirements.txt")
                          dependencies["pip"].extend(pip_deps)
            # Add parsers for other formats (environment.yml) if needed
            else:
                logging.warning(f"Unsupported dependency configuration file type: {config_filename}")

        except Exception as e:
            logging.error(f"Error parsing dependencies from {config_filepath}: {e}")
            # Decide whether to proceed with no dependencies or raise error

        return dependencies


    def _setup_environment(self):
        """Creates the Conda environment using Wetlands if it doesn't exist."""
        if not self.source_dir:
             raise RuntimeError("Source directory not set before environment setup.")

        self.env_name = sanitize_env_name(self.config['name'])
        micromamba_path = self.script_dir / MICROMAMBA_DIR
        logging.info(f"Initializing Environment Manager (micromamba path: {micromamba_path})")
        try:
             # Pass proxy info via environment vars if needed, although .mambarc should be picked up
             self.env_manager = EnvironmentManager(str(micromamba_path))
             logging.info(f"Checking if environment '{self.env_name}' exists...")

             if not self.env_manager.environmentExists(self.env_name):
                 logging.info(f"Environment '{self.env_name}' does not exist. Creating...")
                 dependencies = self._parse_dependencies()
                 if not dependencies.get("pip") and not dependencies.get("conda"):
                      logging.info("No dependencies found. Creating an empty environment.")
                 else:
                      logging.info(f"Installing dependencies: {dependencies}")

                 self.app_env = self.env_manager.create(self.env_name, dependencies=dependencies)
                 logging.info(f"Environment '{self.env_name}' created successfully.")
             else:
                 logging.info(f"Environment '{self.env_name}' already exists.")
                 # Get the environment object for execution
                 self.app_env = self.env_manager.create(self.env_name)

        except Exception as e:
             logging.critical(f"Failed to set up environment '{self.env_name}': {e}")
             # Provide more specific feedback if possible (e.g., download failure, install failure)
             if "Could not solve for environment specs" in str(e):
                  logging.error("This often indicates conflicting dependency versions.")
             elif "Could not download" in str(e) or "HTTP" in str(e):
                  logging.error("This might be a network or proxy issue.")
                  # Consider re-prompting for proxy here if applicable?
             raise


    def _run_application(self):
        """Runs the main application script within its environment."""
        if not self.app_env:
            raise RuntimeError("Environment not set up before running application.")
        if not self.source_dir:
             raise RuntimeError("Source directory not set before running application.")

        main_script_relative = self.config['main']
        main_script_path = self.source_dir / main_script_relative

        if not main_script_path.exists():
            raise FileNotFoundError(f"Main script '{main_script_path}' not found in sources.")

        working_directory = str(self.source_dir)

        # Wetlands expects command arguments relative to the environment activation context
        # It handles activating the env. We just need to tell it to run python.
        # Crucially, we need the *working directory* to be the source dir.
        commands = [f"cd {working_directory}", f"python {main_script_relative}"] # Execute the script name

        logging.info(f"Executing application: '{main_script_path}' in directory '{working_directory}' using environment '{self.env_name}'")

        try:
            # Use executeCommands which allows specifying cwd
            # Wetlands' executeCommands runs commands sequentially in a script.
            process = self.app_env.executeCommands(commands) # Returns subprocess.Popen object

            # Optional: Stream output if needed, or just wait
            # For interactive apps or long-running processes, just waiting might be fine.
            # If you need to see output in real-time (and not using GUI), you might stream it.
            stdout, stderr = process.communicate() # Wait for completion and get output

            if stdout:
                logging.info(f"Application stdout:\n{stdout}")
            if stderr:
                logging.warning(f"Application stderr:\n{stderr}")

            if process.returncode != 0:
                logging.error(f"Application exited with error code {process.returncode}")
                # Optionally raise an exception here
            else:
                logging.info("Application finished successfully.")

        except Exception as e:
            logging.error(f"An unexpected error occurred while running the application: {e}")
            raise

    # ---Error GUI Display Function ---
    def _display_error_gui(self, final_exception: Exception):
        """Displays the final error log in a Textual GUI if available."""
        if not gui_available or not LauncherGUI or not log_queue or not queue_handler:
            logging.info("GUI components not available for error display.")
            return

        logging.info("Attempting to display error log in GUI...")

        # Ensure the critical error message gets into the queue for the GUI
        log_queue.put(f"[bold red]LAUNCHER FAILED:[/bold red] {final_exception}")

        # Attach the queue handler ONLY when launching the GUI
        root_logger = logging.getLogger()
        root_logger.addHandler(queue_handler)

        try:
            app = LauncherGUI()
            app.run() # Runs in main thread, blocks until user quits
        except Exception as e:
            logging.error(f"Failed to run the error display GUI: {e}")
        finally:
            # IMPORTANT: Remove handler after GUI exits
            root_logger.removeHandler(queue_handler)
            logging.info("Error GUI finished.")

    def run(self):
        """Main execution flow of the launcher."""
        start_time = time.monotonic()
        gui_started = False
        proxy_input_requested = False

        try:
            # 1. Handle Network Configuration (Proxies)
            # This might call request_proxy_details_blocking() which runs GUI in main thread
            self._handle_network_config()

            # 2. Determine Version
            self._determine_target_version()

            # 3. Check/Download Sources
            if not self._check_sources_exist():
                logging.info("Sources not found locally.")
                self._download_and_extract_sources()
                # Version in config was already updated by _determine_target_version if needed
            else:
                logging.info("Application sources found locally.")

            # 4. Setup Environment
            self._setup_environment()

            # 5. Run Application
            logging.info("--- Starting Application ---")
            # Optional: Stop the GUI progress display here if desired?
            # Or keep it running to show app logs if wetlands redirects? (Wetlands doesn't easily redirect)

            self._run_application()
            logging.info("--- Application Finished ---")

        except (FileNotFoundError, ValueError, NetworkError, RuntimeError) as e:
            logging.critical(f"LAUNCHER FAILED: {e}")
            # Display error in GUI if possible, otherwise it's just logged to console
            self._display_error_gui(e)
            sys.exit(1) # Exit with error code
        except Exception as e:
            logging.critical(f"An unexpected critical error occurred: {e}", exc_info=True)
            # Display error in GUI if possible
            self._display_error_gui(e)
            sys.exit(1)
        finally:
            # Cleanup? No GUI thread to manage.
            logging.info("Launcher process finished.")


# Custom Exceptions
class NetworkError(Exception):
    """Custom exception for network-related issues."""
    pass

class ProxyRequiredError(Exception):
     """Custom exception to signal the need for proxy input."""
     pass


if __name__ == "__main__":
    launcher = AppLauncher()
    launcher.run()