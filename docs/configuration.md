# Configuration Guide

Each packaged launcher includes one YAML file describing the app it should run.
In an app repository, the default location is
`packaging/launcher/application.yml`.

Validate it with:

```bash
uv run launcher config check
```

## Minimal Example

```yaml
name: MyApp
repository: https://github.com/my-org/myapp.git
entrypoint:
  mode: script
  script: main.py
auto_update: true
configuration: pyproject.toml
# extras:
#   - desktop

trust:
  mode: signed_manifest
  # Replace this with the public key printed by: launcher release keygen
  public_key: "<base64-ed25519-public-key>"
  # With repository set, Launcher infers these GitLab/GitHub release asset URLs.
  # Uncomment only for custom hosting, custom asset paths, or renamed release assets.
  # manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  # signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
  # archive_url: "https://github.com/my-org/myapp/releases/download/{version}/{archive_name}"

# No release.archive config is needed when tracked files are enough.
# For generated assets, uncomment and adjust structured build/include config:
# release:
#   archive:
#     build:
#       - command: ["npm", "ci"]
#         cwd: frontend
#       - command: ["npm", "run", "build"]
#         cwd: frontend
#     include:
#       - frontend/dist
#       - source: frontend/dist
#         destination: my_app/static
# Rare full override fallback:
#     custom_script: packaging/launcher/custom_archive.py
```

## Main Fields

- `name`: display name of your app. Also used to name local data folders.
- `repository`: GitHub or GitLab repository containing your app.
- `gitlab_project_id`: optional numeric GitLab project id. Use this for GitLab
  instances where the project path cannot be resolved by the public API.
- `entrypoint`: how Launcher starts your app. Choose one of `script`,
  `module`, or `project`.
- `path`: optional location for app sources on the user's machine. When omitted
  or null, it defaults to `"."`. Relative paths are resolved inside the
  launcher's per-app runtime data directory, so the default is portable across
  platforms.
- `auto_update`: when true, Launcher checks the latest release.
- `configuration`: dependency file in your app sources, relative to the
  downloaded app archive root. The file must exist. Set `configuration: null`
  only for apps that intentionally have no dependency config file.
- `extras`: optional dependency groups to install from `configuration`.
- `working_directory`: optional app launch directory, relative to the downloaded
  repository root.
- `pythonpath`: optional list of import paths to prepend before starting the
  app, relative to the downloaded app archive root.

## Entrypoint Modes

Use `script` when you want Launcher to run a Python file from the downloaded app archive:

```yaml
entrypoint:
  mode: script
  script: main.py
```

Use `module` when development startup uses `python -m ...`:

```yaml
entrypoint:
  mode: module
  module: my_app
  args:
    - --desktop
    - --port
    - "8765"
```

Use `project` when the app must be installed first, for example because startup
uses a console script, package metadata, entry points, plugins, or packaged data:

```yaml
entrypoint:
  mode: project
  command: my-app-gui
  project_directory: backend
```

In project mode, Launcher installs the project package from `project_directory`, then runs `command`.
Launcher passes the project to Wetlands as an editable local dependency so Pixi and Micromamba can use their own install mechanisms.
The environment is recreated when the app release or project install inputs change.
The project directory should contain a `pyproject.toml` with `[project].name` so Wetlands can name the local package.
If that project declares other local path dependencies, such as `../packages/my-core` in `[project].dependencies`, `[tool.uv.sources]`, or `[tool.pixi.pypi-dependencies]`, those directories must also exist in the downloaded release archive.

If your app code lives below the repository root, use paths from the repository
root:

```yaml
entrypoint:
  mode: module
  module: my_app
  args:
    - --desktop
configuration: backend/pyproject.toml
extras:
  - desktop
```

This is equivalent to installing the dependency file with the optional
`desktop` group. For a `pyproject.toml` managed by `uv`, use the same group name
you would pass to `uv sync --extra desktop`.

By default, Launcher starts the app from the directory containing
`configuration`. In the example above, the working directory is `backend/`.
Launcher also makes that directory importable, and makes `backend/src`
importable when that folder exists. That makes common `src/` Python projects
work without extra config.

For unusual layouts, override those launch paths explicitly:

```yaml
working_directory: backend
pythonpath:
  - backend/src
  - backend/plugins
```

If your repository cannot be inferred automatically, you can use explicit API
fields for release discovery instead of `repository`:

```yaml
api: https://api.github.com
releases_endpoint: /repos/my-org/myapp/releases/latest
```

Archive downloads come from the signed manifest's `archive.url`, not from provider source archive endpoints.

For GitLab, Launcher uses API v4. A project path such as
`group/myapp` is sent to GitLab as `group%2Fmyapp`, which is the normal GitLab
API format. If GitLab returns `404 Project Not Found`, check that the project is
publicly visible to the packaged app. For private or restricted self-hosted
GitLab projects, prefer the numeric project id:

```yaml
repository: https://gitlab.example.org/my-group/myapp
gitlab_project_id: "123456"
```

## Security Fields

The `trust` section tells Launcher how to verify downloaded app sources.
Generate the key with:

```bash
uv run launcher release keygen
```

The command writes `launcher-signing-key.pem`, adds it to `.gitignore`, and
prints the `public_key` value. Replace the placeholder in
`packaging/launcher/application.yml` with the printed value; `keygen` does not
edit the config file.

```yaml
trust:
  mode: signed_manifest
  # Replace this with the public key printed by: launcher release keygen
  public_key: "<base64-ed25519-public-key>"
  # With repository set, Launcher infers these GitLab/GitHub release asset URLs.
  # Uncomment only for custom hosting, custom asset paths, or renamed release assets.
  # manifest_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml"
  # signature_url: "https://github.com/my-org/myapp/releases/download/{version}/launcher-manifest.yml.sig"
  # archive_url: "https://github.com/my-org/myapp/releases/download/{version}/{archive_name}"
```

This is required because Launcher downloads Python code and runs it. See
[security.md](security.md) for the explanation.

When `repository` is set to a GitHub or GitLab repository, Launcher infers the default runtime release asset URL templates.
Those defaults point to `launcher-manifest.yml`, `launcher-manifest.yml.sig`, and the versioned archive uploaded by `launcher release upload`.
`launcher release sign` uses the inferred archive URL to write the exact app archive URL into the signed manifest.
At runtime, Launcher downloads `archive.url` from the verified manifest and checks its SHA-256 hash before extraction.
Configure `manifest_url`, `signature_url`, and `archive_url` only for custom hosting, custom asset paths, renamed files, or endpoint-only configs that do not set `repository`.
`{version}` is replaced with the release tag the launcher is trying to run, and `{archive_name}` is replaced with the archive filename in `dist/`.

## Release Tag

Release publishing commands read the static `[project].version` from the TOML file named by `configuration`.
The exact project version is the release tag by default, so project version `1.2.3` produces tag `1.2.3`.

Projects that deliberately use another tag convention can configure one template:

```yaml
release:
  tag_template: "v{version}"
```

The template must contain exactly one `{version}` placeholder and produce a Git tag that is safe inside an artifact filename.
Explicit CLI tags remain available when project inference is unavailable, and must exactly match project metadata when both are present.

## Release Archive Fields

`release.archive` is optional packaging-only config read by `launcher release archive`.
When it is omitted, Launcher creates `dist/<repo>-<tag>.zip` from tracked files at the resolved tag.
The requested ref must resolve to `HEAD`, and tracked files must be clean before and after packaging.

Use `build` for generated assets that are not tracked by git:

```yaml
release:
  archive:
    build:
      - command: ["npm", "ci"]
        cwd: frontend
      - command: ["npm", "run", "build"]
        cwd: frontend
    include:
      - frontend/dist
      - source: frontend/dist
        destination: my_app/static
```

Each `command` is an argv list run with `shell=False`.
`cwd` is optional and relative to the repository root.
String `include` entries preserve the source path in the archive.
Object `include` entries copy `source` to `destination`, where `destination` is relative to the archive root.

For rare cases where structured config is not enough, set `custom_script` to a Python script path:

```yaml
release:
  archive:
    custom_script: packaging/launcher/custom_archive.py
```

The script is called as `python <script> <version> <archive_path>` and must create the requested zip archive.
`custom_script` cannot be combined with `build` or `include`.

## Optional Fields

```yaml
version: 1.2.3
entrypoint:
  mode: module
  module: my_app
  args:
    - --desktop
working_directory: backend
pythonpath:
  - backend/src
install: install.py
reinstall_on_update: false
gui_timeout: 3
init_message: "Initialized"
init_timeout: 30
```

- `version`: fixed version to use when `auto_update` is false.
- `entrypoint.args`: arguments passed to the configured script, module, or
  project command.
- `working_directory`: override the inferred app launch directory.
- `pythonpath`: override inferred Python import paths.
- `install`: optional Python install script in your app sources.
- `reinstall_on_update`: rerun the install script after an update.
- `gui_timeout`: seconds before showing a progress window.
- `init_message`: optional text printed by your app when it is ready.
- `init_timeout`: how long to wait for `init_message` when it is configured.

Without `init_message`, Launcher starts the app, checks that it does not exit
immediately, then exits and leaves the app running.

With `init_message`, Launcher keeps watching the app output until that text is
printed. If the timeout expires, the user can keep waiting, reinstall the local
environment, or exit. Reinstalling may fix a corrupted local environment, but it
will not fix a broken release; publish a fixed release and restart Launcher in
that case.

## Runtime State

Launcher does not edit the packaged YAML file during normal use.

Values that change, such as the installed version, dependency hash, and proxy
settings, are saved in the user's app data folder:

- macOS: `~/Library/Application Support/<AppName>/launcher-state.yml`
- Windows: `%APPDATA%\<AppName>\launcher-state.yml`
- Linux: `~/.local/state/<AppName>/launcher-state.yml`

Downloaded app sources are stored under the configured `path`. With the default
`path: "."`, sources are stored beside the launcher state in the same per-app
runtime data directory, with one subfolder per version:

- macOS: `~/Library/Application Support/<AppName>/<appname>-<version>/`
- Windows: `%APPDATA%\<AppName>\<appname>-<version>\`
- Linux: `~/.local/state/<AppName>/<appname>-<version>/`

The launcher never writes downloaded sources inside the signed `.app` bundle.

Proxy passwords are not stored in YAML. If the user chooses to remember a proxy
password, Launcher stores it in the operating system keychain.
