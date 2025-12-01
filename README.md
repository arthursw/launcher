# Application Launcher

A Python launcher that automatically manages downloads, updates, and execution of applications specified in a configuration file.

## Features

- **Dependency Installation**: Installs dependencies from `pyproject.toml` or other configuration files
- **Auto-Update**: Automatically fetches the latest version from GitHub or GitLab
- **Environment Management**: Creates isolated Python environments using conda/micromamba
- **Proxy Support**: Handles proxy configuration for enterprise environments
- **Multiple GUI Options**: Choose from Console, Tkinter, Qt, or Textual interfaces

## Quick Start

### Installation

```bash
uv sync
```

### Basic Usage

Run with default console GUI:
```bash
uv run main.py
```

Choose a specific GUI:
```bash
uv run main.py --gui tkinter
uv run main.py --gui textual
uv run main.py --gui qt
uv run main.py --gui console
```

Specify a config file:
```bash
uv run main.py --config /path/to/application.yml
```

## Configuration

### Install Script (Optional)

The launcher supports running a custom install script after dependencies are installed but before the main application launches. This is useful for additional setup tasks that cannot be handled by the dependency configuration file.

To use an install script:

1. Create an install script (e.g., `install.sh`) in your application sources
2. Add the `install` attribute to your `application.yml`:
   ```yaml
   install: install.sh
   ```

The script will be executed in the application's conda environment with bash. For example:

```bash
#!/bin/bash
# Custom installation steps
npm install
python setup.py build
make configure
```

**Note**: The install script path is relative to the extracted sources directory. If the script is not found, it will be skipped with a warning.

## Application Configuration

Create an `application.yml` file next to the launcher executable with the following structure:

```yaml
name: ExampleApp                                      # Application name (used for environment name)
repository: git@github.com:owner/exampleapp.git       # Git repository URL (optional, see note below)
api: https://api.github.com/                          # API URL (optional if repository is provided)
tags_endpoint: /repos/owner/exampleapp/git/tags       # Endpoint to get version tags (optional if repository is provided)
archive_endpoint: /repos/owner/exampleapp/zipball/{ref}  # Endpoint to download sources (optional if repository is provided)
main: main.py                                         # Main script to execute
path: "."                                             # Directory to extract sources
version: exampleapp-v0.3.50                           # Current version
auto_update: true                                     # Auto-update to latest version
configuration: pyproject.toml                         # Dependency configuration file
install: install.sh                                   # Optional install script to run after env setup
timeout: 3                                            # Seconds before showing GUI
proxy_servers:                                        # Optional proxy settings
  http: http://username:password@proxy.com:8080
  https: https://username:password@proxy.com:8443
```

### Repository Configuration

You can simplify configuration by using the `repository` attribute instead of specifying `api`, `tags_endpoint`, and `archive_endpoint` individually:

**Option 1: Using repository (simpler)**
```yaml
name: ExampleApp
repository: git@github.com:owner/exampleapp.git
main: main.py
path: "."
version: exampleapp-v0.3.50
auto_update: true
configuration: pyproject.toml
```

**Option 2: Using explicit endpoints (for custom APIs)**
```yaml
name: ExampleApp
api: https://api.github.com/
tags_endpoint: /repos/owner/exampleapp/git/tags
archive_endpoint: /repos/owner/exampleapp/zipball/{ref}
main: main.py
path: "."
version: exampleapp-v0.3.50
auto_update: true
configuration: pyproject.toml
```

#### Supported Repository Formats

The launcher supports both SSH and HTTPS repository URLs:

**GitHub**
- SSH: `git@github.com:owner/repository.git`
- HTTPS: `https://github.com/owner/repository.git`

**GitLab**
- SSH: `git@gitlab.com:owner/repository.git`
- HTTPS: `https://gitlab.com/owner/repository.git`
- On-premise: `git@gitlab.inria.fr:owner/repository.git`

**Generic Git hosts**
- SSH: `git@host.com:owner/repository.git`
- HTTPS: `https://host.com/owner/repository.git`

The `.git` suffix is optional for all formats.

#### Notes

- Configuration must include either `repository` OR all three of (`api`, `tags_endpoint`, `archive_endpoint`)
- If `repository` is provided, the API endpoints are automatically inferred
- Explicit `api`, `tags_endpoint`, and `archive_endpoint` values take priority over inferred values from `repository`
- For custom or non-standard APIs, use the explicit endpoint configuration

## Architecture

### Core Components

```
launcher/
  launcher.py          # Main launcher orchestration
  proxy.py            # Proxy configuration handling
  worker.py           # Worker thread for background operations
  main.py             # CLI entry point
  gui/
      base_gui.py     # Abstract GUI base class
      console_gui.py  # Console/terminal UI
      tkinter_gui.py  # Tkinter GUI
      qt_gui.py       # Qt (PyQt5) GUI
      textual_gui.py  # Textual TUI
  tests/
      test_launcher.py
      test_proxy.py
      test_gui_base.py
      test_worker.py
```

### Execution Flow

1. **Initialization**: Load `application.yml` configuration
2. **Version Check**:
   - If `auto_update: true`, fetch latest version from API
   - Otherwise, use version from config
3. **Source Management**:
   - Check if sources exist locally
   - Download if needed
4. **Environment Setup**:
   - Create conda environment if it doesn't exist
   - Install dependencies from configuration file
5. **Install Script** (optional):
   - Run install script in environment if `install` attribute is defined
   - Script path is relative to the extracted sources
6. **Execution**: Run the main application script

### Threading Model

- **Main Thread**: Runs the selected GUI
- **Worker Thread**: Performs I/O operations (downloads, env setup)
- **Queue-Based Communication**: Thread-safe event passing via `queue.Queue`

## GUI Options

### Console GUI
Simple console-based interface using Python's `input()` and `print()`. Good for CLI-only environments.

```bash
uv run main.py --gui console
```

### Tkinter GUI
Cross-platform GUI with progress bar and log display. Built-in to Python.

```bash
uv run main.py --gui tkinter
```

### Qt GUI
Modern Qt interface (requires PyQt5). Rich UI with progress bar and log viewer.

```bash
uv run main.py --gui qt
```

### Textual GUI
Modern TUI for terminal environments. Beautiful terminal-based UI.

```bash
uv run main.py --gui textual
```

## Proxy Configuration

The launcher automatically detects proxy settings from:
1. `application.yml` file (`proxy_servers` section)
2. Conda configuration files (`.condarc`, `.mambarc`)
3. User input (if not found in above)

Proxy settings are saved to `application.yml` for future use.

## Testing

Run the full test suite:
```bash
uv run pytest tests/ -v
```

Run specific test file:
```bash
uv run pytest tests/test_launcher.py -v
```

Run with coverage:
```bash
uv run pytest tests/ --cov=. --cov-report=html
```

## Development

### Project Structure

- **Separation of Concerns**: Each module has a single responsibility
- **Dependency Injection**: GUI receives launcher, queues, etc.
- **Abstract Interfaces**: BaseGUI allows multiple implementations
- **Thread-Safe Queues**: All thread communication via `queue.Queue`

### Adding a New GUI

1. Create new file in `gui/` directory
2. Inherit from `BaseGUI`
3. Implement `show_proxy_dialog()` and `run()` methods
4. Register in `main.py`'s `get_gui_class()` function

Example:
```python
from gui.base_gui import BaseGUI

class NewGUI(BaseGUI):
    def show_proxy_dialog(self) -> dict:
        # Implement proxy dialog
        return {"http": "...", "https": "..."}

    def run(self) -> None:
        # Implement GUI main loop
        pass
```

## API Support

### GitHub
```yaml
api: https://api.github.com/
tags_endpoint: /repos/owner/project/git/tags
archive_endpoint: /repos/owner/project/zipball/{ref}
```

### GitLab
```yaml
api: https://gitlab.com/api/v4/
tags_endpoint: /projects/{projectId}/repository/tags
archive_endpoint: /projects/{projectId}/repository/archive.zip
```

## Environment Variables

- `CONDA_ROOT`: Path to conda root (if using conda instead of micromamba)
- `MAMBA_ROOT_PREFIX`: Path to micromamba root
- `CONDA_PREFIX`: Current conda environment prefix

## Troubleshooting

### "Could not find application.yml"
Ensure `application.yml` is in the current directory or next to the launcher executable.

### Network errors behind proxy
Either:
1. Add `proxy_servers` to `application.yml`
2. Configure conda with proxy settings in `.condarc`
3. The launcher will prompt for proxy settings when needed

### Environment creation fails
Check that `pyproject.toml` exists in the downloaded sources and contains valid Python dependencies.

### GUI not showing
If the operation completes faster than the `timeout` setting, no GUI appears. Set `timeout: 0` to always show GUI.

## Dependencies

- **pyyaml**: Configuration file parsing
- **requests**: HTTP requests for downloading sources
- **textual**: Terminal UI framework
- **toml**: TOML file parsing
- **wetlands**: Python environment management via conda/micromamba

### Optional Dependencies

- **PyQt5**: For Qt GUI
- **pytest**: For running tests
- **pytest-cov**: For test coverage

## License

See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass: `uv run pytest tests/`
5. Submit a pull request

## Limitations

- Currently supports Python 3.10+
- Environment management via conda/micromamba only
- Requires application sources to have a supported dependency file (`pyproject.toml`, etc.)

## Future Enhancements

- Support for other package managers (pip, poetry, etc.)
- Configuration validation before execution
- Update notification without automatic update
- Application rollback to previous version
- Scheduled automatic updates
- Multi-language support in GUI
