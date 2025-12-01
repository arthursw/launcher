Create a launcher app in python, which launches and auto-updates an application (specified by a `application.yml` file).

Its primary goal is to ensure the application's source code is present and up-to-date, set up the necessary Python environment, and then launch the main application (run the main script located in the downloaded sources).

This launcher will be packaged into an executable with PyInstaller (or cxFreeze).

With this launcher, it will be extremely easy for a developper to ship his app: just create a zip containing the launcher executable and the `application.yml` filled with the settings of the application to launch.


The `application.yml` will look as follow:
```yaml
name: ExampleApp                                                         # The name of the application (used for the environment name)
repository: git@github.com:owner/exampleapp.git                          # The git repository URL (optional if api, tags_endpoint, and archive_endpoint are provided)
api: https://api.github.com/                                             # The API URL to get tags and sources (optional if repository is provided)
tags_endpoint: /repos/owner/exampleapp/git/tags                          # The API endpoint to get the list of tags (optional if repository is provided)
archive_endpoint: /repos/owner/exampleapp/zipball/{ref}                  # The API endpoint to get the sources archive (optional if repository is provided)
main: main.py                                                            # The main script to execute in the sources
path: "."                                                                # The directory in which to extract the sources (could be "~/Applications/")
version: exampleapp-v0.3.50-295e42238d99f3e133cb0e788d6fb4d7a8139d31     # The version of the installed app
auto_update: true                                                        # Whether to auto-update if a new version is available on github or gitlab
configuration: pyproject.toml                                            # The configuration file to look for the dependencies. Can be a pyproject.toml, pixi.toml, environment.yml or requirements.txt file.
install: run.sh                                                          # The install script with additional install commands
gui_timeout: 3                                                           # The time (in seconds) before opening the GUI which displays what's happening
init_message: "Initialized"                                              # The message confirming the app is initialized (so the app is installed properly)
init_timeout: 30                                                         # The time (in seconds) before throwing an "Install error" when waiting the init message
proxy_servers:                                                           # The proxy settings to use if behind a proxy (undefined by default, and set by the user if necessary)
  http: http://username:password@corp.com:8080
  https: https://username:password@corp.com:8080
```

### Repository Attribute

The `repository` attribute allows simplifying configuration by automatically inferring the API endpoints. Instead of specifying `api`, `tags_endpoint`, and `archive_endpoint` separately, you can provide a single `repository` attribute:

- The launcher will parse the repository URL and infer the API endpoints for GitHub, GitLab, or generic git hosts
- Supported formats:
  - SSH: `git@github.com:owner/repo.git`
  - HTTPS: `https://github.com/owner/repo.git`
  - The `.git` suffix is optional

- If both `repository` and explicit endpoints are provided, the explicit endpoints take priority

Examples:

**GitHub (simplified)**
```yaml
name: MyApp
repository: git@github.com:myorg/myapp.git
main: main.py
path: "."
version: myapp-v1.0.0
auto_update: true
configuration: pyproject.toml
```

**GitLab on-premise with override**
```yaml
name: MyApp
repository: git@gitlab.inria.fr:myorg/myapp.git
api: https://my-custom-api.com/  # Overrides the inferred GitLab API
tags_endpoint: /repos/owner/exampleapp/git/tags                          # The API endpoint to get the list of tags (optional if repository is provided)
archive_endpoint: /repos/owner/exampleapp/zipball/{ref}                  # The API endpoint to get the sources archive (optional if repository is provided)
main: main.py
path: "."
version: myapp-v1.0.0
auto_update: true
configuration: pyproject.toml
```


This launcher will:
- read the `application.yml` file located beside the launcher executable
- if `auto_update`: check the latest tag from `api`/`tags_endpoint` and set the current version from this latest tag in the following format: `appname-tagname`
- otherwise: set the current version from the `version` attribute
- check if the sources for this current version (`appname-tagname`) exist at `path` (if a folder named `appname-tagname` exists at the `path` location)
- if the sources do not exist: download them from the `archive_endpoint` and extract them in the `path`
- update `application.yml` to set the current version in `version`
- get or create the environment and execute the main script: 
  - check if the ExampleApp environment exists (remove special chars from the name to make it a valid env name)
  - if the environment does not exists: 
    - create the environment and install the dependencies defined in the `configuration` file in the sources (parse the `path`/`appname-tagname`/`configuration` file, usually a `pyproject.toml`, but can also be a `pixi.toml`, `environment.yml` or `requirements.txt` file.)
    - run the install script defined by the `install` attribute if any
- run the main script defined by the `main` attribute (located in `path`/`appname-tagname`)
- read the stdout and wait for the `init_message`: it will confirm the app is properly installed
- if the `init_message` is not in the stdout for `init_timeout` seconds: ask the user to either delete the environment (to trigger a new installation when restarting the app), or exit, or wait more

## Python environment management

The wetlands library will be used to set up the python environment.

The following enables to create a python environment with wetlands:
```python
from wetlands.environment_manager import EnvironmentManager

logging.basicConfig(level=logging.INFO)

# Initialize the environment manager (will download and install pixi at `pixi/`)
environmentManager = EnvironmentManager()

# Create and launch a Conda environment named "numpy_env"
env = environmentManager.create("numpy_env", {"pip": ["numpy==2.2.4"]})

# Alternatively, it is possible to provide a pyproject.toml file:
# env = environmentManager.createFromConfig("numpy_env", "path/to/pyproject.toml")

# This will be executed in the environment, by creating a bash or powershell script which activates the env and executes the commands (here )
env.executeCommands(["python downloaded_sources/main.py"])
```

## Proxy settings

The launcher will need to access the internet to get the latest tags and sources. If it is behind a proxy, it might not work. If it does not work, the launcher will check the conda / mamba proxy settings in the following files:
```python
condaConfigurations = ["/etc/conda/.condarc",
                    "/etc/conda/condarc",
                    "/etc/conda/condarc.d/",
                    "/etc/conda/.mambarc",
                    "/var/lib/conda/.condarc",
                    "/var/lib/conda/condarc",
                    "/var/lib/conda/condarc.d/",
                    "/var/lib/conda/.mambarc"] if platform.system() != 'Windows' else [
                    "C:\\ProgramData\\conda\\.condarc",
                    "C:\\ProgramData\\conda\\condarc",
                    "C:\\ProgramData\\conda\\condarc.d",
                    "C:\\ProgramData\\conda\\.mambarc"
                    ]

condaConfigurations += [
    "$CONDA_ROOT/.condarc",
    "$CONDA_ROOT/condarc",
    "$CONDA_ROOT/condarc.d/",
    "$MAMBA_ROOT_PREFIX/.condarc",
    "$MAMBA_ROOT_PREFIX/condarc",
    "$MAMBA_ROOT_PREFIX/condarc.d/",
    "$MAMBA_ROOT_PREFIX/.mambarc",
    "$XDG_CONFIG_HOME/conda/.condarc",
    "$XDG_CONFIG_HOME/conda/condarc",
    "$XDG_CONFIG_HOME/conda/condarc.d/",
    "~/.config/conda/.condarc",
    "~/.config/conda/condarc",
    "~/.config/conda/condarc.d/",
    "~/.conda/.condarc",
    "~/.conda/condarc",
    "~/.conda/condarc.d/",
    "~/.condarc",
    "~/.mambarc",
    "$CONDA_PREFIX/.condarc",
    "$CONDA_PREFIX/condarc",
    "$CONDA_PREFIX/condarc.d/",
    "$CONDARC",
    "$MAMBARC"
]
condaConfigurations += [
    "micromamba/.condarc",
    "micromamba/condarc",
    "micromamba/condarc.d/",
    "micromamba/.mambarc",
]
```

If there are no proxy settings found (or none is working), the launcher opens a simple dialog for the user to enter the proxy settings. Once the user enters its proxy settings, the launcher saves them in `application.yml`, and continue.

## GUI

The launcher should only open a GUI if necessary: to enter the proxy settings or if the application launch time is too long (the launch duration is greater than `timeout`) to show a progress bar and the logs (downloads, installation, env creation, etc. ).

The GUI should be made with Tkinter. The issue is that the GUI must run in the main thread. This means there must be two threads: the main one for the GUI, and a second one for everything else. They must communicate: the main GUI provides the proxy settings if required, the other thread tells about the logs / download / loading progress.

## Alternative launchers

Other launchers will be avaible: 
- the Qt launcher, which will use Qt for the GUI
- the Textual launcher. which will use the Textual library for the GUI
- the console / no GUI launcher, which won't use any GUI, but the python's input() function for the proxy settings



#  Implementation Strategy

1. Shared Data Structure (Thread-Safe Queue)
Use queue.Queue (thread-safe) to pass messages from worker → GUI:
import queue
from threading import Thread

# Shared queue for worker → GUI communication
event_queue = queue.Queue()

# Worker thread sends events like:
event_queue.put({
    'type': 'progress',
    'current': 45,
    'total': 100,
    'message': 'Downloading sources...'
})

event_queue.put({
    'type': 'log',
    'message': 'Installation complete'
})

event_queue.put({
    'type': 'proxy_required',
    'request_id': uuid.uuid4()  # For response tracking
})

2. GUI → Worker Communication (Events)
For sending proxy settings or cancellation:
# GUI collects proxy settings and sends back
response_queue = queue.Queue()

response_queue.put({
    'type': 'proxy_settings',
    'http': 'http://proxy:8080',
    'https': 'https://proxy:8080'
})

# Worker thread listens
proxy_settings = response_queue.get(timeout=30)  # Wait 30 seconds

3. GUI Integration (Textual Example)
class LauncherApp(App):
    def on_mount(self):
        # Start worker thread
        self.worker_thread = Thread(target=self.launcher_worker, daemon=True)
        self.worker_thread.start()

        # Periodically check event queue
        self.set_interval(0.1, self.check_events)

    def check_events(self):
        try:
            event = event_queue.get_nowait()
            if event['type'] == 'progress':
                self.update_progress(event['current'], event['total'])
            elif event['type'] == 'log':
                self.append_log(event['message'])
            elif event['type'] == 'proxy_required':
                self.show_proxy_dialog(event['request_id'])
        except queue.Empty:
            pass

    def on_proxy_dialog_submit(self, settings):
        response_queue.put({'type': 'proxy_settings', 'data': settings})

def launcher_worker():
    try:
        # Try normal operations
        result = check_update()
        event_queue.put({'type': 'log', 'message': f'Found version {result}'})
    except NetworkError:
        # Request proxy settings from GUI
        event_queue.put({'type': 'proxy_required'})
        settings = response_queue.get(timeout=30)
        # Retry with proxy...

Key Design Points

- Queue-based: No direct thread manipulation, just put/get messages
- Non-blocking: GUI stays responsive with get_nowait() or short timeouts
- Unique IDs: For tracking which dialog response corresponds to which request
- Error handling: Worker thread catches all exceptions and sends error events
- Timeout protection: Prevent GUI freeze if worker hangs (use timeout parameter)

This ensures the GUI remains responsive while the worker performs I/O-bound operations (downloads, environment setup).
