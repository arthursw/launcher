Create a launcher app in python, which launches and auto-updates an application (specified by a `application.yml` file).

Its primary goal is to ensure the application's source code is present and up-to-date, set up the necessary Python environment, and then launch the main application (run the main script located in the downloaded sources).

This launcher will be packaged into an executable with PyInstaller (or cxFreeze).

With this launcher, it will be extremely easy for a developper to ship his app: just create a zip containing the launcher executable and the `application.yml` filled with the settings of the application to launch.


The `application.yml` will look as follow:
```yaml
name: ExampleApp                                                         # The name of the application (used for the environment name)
api: https://api.github.com/                                             # The API URL to get tags and sources (could be something like `https://gitlab.inria.fr/api/v4/`)
tags_endpoint: /repos/owner/exampleapp/git/tags                          # The API endpoint to get the list of tags (`projects/{projectId}/repository/tags` on Gitlab)
archive_endpoint: /repos/owner/exampleapp/zipball/{ref}                  # The API endpoint to get the sources archive  (`projects/{projectId}/repository/archive.zip` on Gitlab)
main: main.py                                                            # The main script to execute in the sources
path: "."                                                                # The directory in which to extract the sources (could be "~/Applications/")
version: exampleapp-v0.3.50-295e42238d99f3e133cb0e788d6fb4d7a8139d31     # The version of the installed app
auto_update: true                                                        # Whether to auto-update if a new version is available on github or gitlab
project: exampleapp                                                      # The project id (on Gitlab) or name (on Github)
configuration: pyproject.toml                                            # The configuration file to look for the dependencies
timeout: 3                                                               # The time before opening the GUI which displays what's happening
proxy_servers:                                                           # The proxy settings to use if behind a proxy (undefined by default, and set by the user if necessary)
  http: http://username:password@corp.com:8080
  https: https://username:password@corp.com:8080
gui: qt                                                                  # The gui framework to use, can be Textual, Qt, Tkinter or none (console)
```


This launcher will:
- read the `application.yml` file located beside the launcher executable
- if `auto_update`: check the latest tag from `api`/`tags_endpoint` and set the current version from this latest tag in the following format: `appname-tagname`
- otherwise: set the current version from the `version` attribute
- check if the sources for this current version (`appname-tagname`) exist at `path` (if a folder named `appname-tagname` exists at the `path` location)
- if the sources exist, create an environment if necessary and execute the main script: 
  - check if the ExampleApp environment exists (remove special chars from the name to make it a valid env name)
  - if the environment does not exists: create the environment and install the dependencies defined in the `configuration` file in the sources (parse the `path`/`appname-tagname`/`configuration` file, usually a `pyproject.toml`)
  - run the main script defined by the `main` attribute (located in `path`/`appname-tagname`)
- otherwise: download them from the `archive_endpoint` and extract them in the `path`
- update `application.yml` to set the current version in `version`
- create an environment if necessary and execute the main script as described above

## Python environment management

The wetlands library will be used to set up the python environment.

The following enables to create a python environment with wetlands:
```python
from wetlands.environment_manager import EnvironmentManager

# Initialize the environment manager (will download and install micromamba at `micromamba/`)
environmentManager = EnvironmentManager("micromamba/")

# Create and launch a Conda environment named "numpy_env"

# This will run a bash script or powershell script which runs commands like:
#   export MAMBA_ROOT_PREFIX="/path/to/examples/micromamba"
#   eval "$(bin/micromamba shell hook -s posix)"
#   micromamba --rc-file "/path/to/examples/micromamba/.mambarc" create -n numpy_env
#   pip install numpy==2.2.4 -y
env = environmentManager.create("numpy_env", {"pip": ["numpy==2.2.4"]})

# This will be executed in the environment, by creating a bash or powershell script which runs commands like:
#   export MAMBA_ROOT_PREFIX="/path/to/examples/micromamba"
#   eval "$(bin/micromamba shell hook -s posix)"
#   micromamba activate numpy_env
#   python downloaded_sources/main.py
env.executeCommands("python downloaded_sources/main.py")
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

If there are no proxy settings found (or none is working), the launcher opens a simple dialog for the user to enter the proxy settings. Once the user enters its proxy settings, the launcher saves them in `application.yml`, updates `micromamba/.mambarc`, and continue.

## GUI

The launcher should only open a GUI if necessary: to enter the proxy settings or if the application launch time is too long (the launch duration is greater than `timeout`) to show a progress bar and the logs (downloads, installation, env creation, etc. ).

The GUI should be made with the Textual library, Qt or Tkinter. The issue is that the GUI must run in the main thread. This means there must be two threads: the main one for the GUI, and a second one for everything else. They must communicate: the main GUI provides the proxy settings if required, the other thread tells about the logs / download / loading progress.

It is also possible to disable the gui (gui: "none"), in which case everything happens in the console, and the proxy settings will be requested with python's `input()` function.

For now, just explain how the main thread and the other thread will communicate when using a GUI.