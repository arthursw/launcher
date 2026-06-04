# Launcher Packaging Workflow Progress

## Initial plan

- Make `packaging/launcher/application.yml` the app-repo default config.
- Add unified `launcher` subcommands: `run`, `init`, `build`, and `release`.
- Expose release operations only as `launcher release ...`.
- Keep launcher executable build artifacts separate from app release artifacts.

## Iteration 1

- Planned: add tests for new config defaults, unified release command dispatch, init generation, and build spec planning.
- Implemented:
  - Added `packaging/launcher/application.yml` runtime and release defaults.
  - Added unified `launcher run`, `launcher init`, `launcher build`, and `launcher release ...` dispatch.
  - Removed the separate release entry point; release operations live under `launcher release ...`.
  - Added `launcher build --spec-only` with generated files under `dist/launcher/`.
  - Updated app-repo workflow docs and examples.
- Learned:
  - `launcher.gui.__init__` imported optional GUI backends eagerly, which broke base `pytest` collection without Textual installed.
  - Generated build artifacts belong under `dist/launcher/`, not under app-owned `packaging/launcher/`.
- Plan changes:
  - Fixed GUI package exports to import optional backends lazily.
  - Generated init trust URLs now infer GitHub owner/repo from the supplied repository when possible.
- Next: review final diffs and handle any review-agent findings.

## Iteration 2

- Planned: investigate the first real app-repo build run and fix any workflow gaps exposed by it.
- Implemented:
  - Generated PyInstaller specs now keep absolute source paths for bundled config data and icons.
  - `launcher init` now generates `path: "."`.
  - Relative source install paths are resolved inside the launcher's per-app runtime data directory.
  - Self-hosted GitLab repositories now get GitLab release asset URLs during `launcher init`.
  - README, packaging docs, configuration docs, specs, and example config now explain keygen, trust URLs, and `path: "."`.
- Learned:
  - PyInstaller resolves relative data paths from the generated spec directory, not from the app repository root.
  - Changing `repository` after `launcher init` can leave stale manifest/signature URLs.
- Plan changes:
  - Keep generated configs portable by using `path: "."`, with runtime path resolution handled by Launcher.
  - Prefer passing the real repository to `launcher init` so trust URLs are generated correctly.
- Review findings handled:
  - Added `launcher.paths` to centralize runtime data paths used by state and relative source installs.
  - Extended repository parsing and init URL inference for GitLab nested groups.
- Next: run focused and full verification.

## Iteration 3

- Planned: make the generated `application.yml` explain the next release commands directly.
- Implemented:
  - Added inline comments before `trust.public_key` explaining that `launcher release keygen` prints the replacement value.
  - Added inline comments before manifest/signature URLs explaining that they match the default `launcher release sign` and `launcher release upload` workflow.
  - Mirrored the generated comments in the example config and YAML snippets in the docs.
- Learned:
  - Generated config comments should mention launcher subcommands, not a specific invocation wrapper such as `uv run`.
- Plan changes:
  - Keep inline generated guidance short and command-focused.
- Next: run focused and full verification.

## Iteration 4

- Planned: remove the fragile generated placeholder PNG and add a proper icon workflow.
- Implemented:
  - Added `assets/launcher-spaceship-icon.svg` as editable source artwork for review.
  - Stopped creating `icon_128x128.png` by default in `launcher init`.
  - Added `launcher init --icon` to copy `.icns`, `.ico`, or `.png` files to canonical packaging names.
  - Added `launcher build --icon` for one-off generated spec icon overrides.
  - Changed macOS auto-discovery to use only `app.icns`, avoiding implicit PNG-to-ICNS conversion through Pillow.
  - Updated README and packaging docs for custom icon use.
- Learned:
  - The embedded 1x1 PNG was invalid enough to trip Pillow during PyInstaller macOS bundle icon conversion.
- Plan changes:
  - Treat SVG as source artwork, not as direct PyInstaller icon input.
- Next: run focused and full verification.

## Iteration 5

- Planned: make GitLab update failures clearer after a packaged app hit `404 Project Not Found`.
- Implemented:
  - Added `gitlab_project_id` config support so GitLab projects can use numeric ids instead of path-based ids.
  - Split HTTP status failures from proxy/network failures.
  - Stopped routing HTTP 404/401/403-style release API responses through the proxy prompt path.
  - Documented GitLab v4 path encoding, public visibility, and numeric project id fallback.
- Learned:
  - `gitlab.inria.fr` does expose API v4, but the unauthenticated path-based release endpoint returns `404 Project Not Found` for the reported project.
- Plan changes:
  - Keep GitLab path inference as the default, but provide a numeric project id escape hatch for self-hosted/private deployments.
- Next: run focused and full verification.

## Iteration 6

- Planned: clarify the release publication guide without adding release creation/download automation.
- Implemented:
  - Expanded the packaging guide's app-update section into explicit release, archive download, sign, verify, and upload steps.
  - Added minimal `gh` and `glab` command examples for release creation and source archive download.
  - Corrected the `glab repo archive` example to pass the project path before the output directory.
  - Added optional direct `gh release upload` and `glab release upload` equivalents for the generated manifest assets.
  - Linked to the official GitHub CLI and GitLab CLI command references.
  - Reworked the update publishing guide into separate release creation, archive download, sign/verify, and metadata upload subsections.
  - Clarified that release creation and archive download remain provider-owned, while manifest/signature generation and upload are Launcher-owned.
- Learned:
  - Keeping release creation and archive download outside Launcher keeps authentication, release notes, and archive selection explicit.
  - The GitLab archive command is clearer when the project path is shown explicitly.
  - `launcher release upload` should be documented as the default metadata upload path, with provider CLI upload commands only as manual alternatives.
- Plan changes:
  - Do not add release creation or archive download to Launcher yet.
- Next: decide separately whether `path` should become optional instead of using `path: "."`.

## Iteration 7

- Planned: remove project-specific examples and make release CLI references easier to find.
- Implemented:
  - Replaced the remaining project-specific examples in docs and tests with neutral sample app paths.
  - Moved GitHub/GitLab CLI reference links next to the release, archive download, and upload commands they explain.
  - Added self-hosted GitLab `glab auth login --hostname ...` guidance near the GitLab release commands.
  - Converted release references to inline Markdown links placed after the typical command examples.
  - Added web UI links for manual GitHub/GitLab release creation and source archive download.
- Learned:
  - The publishing guide reads better when references are placed at the point where the user chooses a provider command.
- Next: run final searches and focused verification.

## Iteration 8

- Planned: fix the GitLab archive workflow after `glab repo archive ... dist` produced `dist.zip`.
- Implemented:
  - Changed the GitLab packaging guide example to write a versioned archive filename and then move it into `dist/`.
  - Documented that default version inference comes from the archive filename and that `--version` is required for unversioned archives.
  - Improved the `launcher release sign` error when a selected archive has no version in its filename.
  - Added tests for explicit `--version` with an unversioned archive and for conservative filename inference.
- Learned:
  - `glab repo archive` treats its output argument as an archive filename, not a destination directory.
  - Provider archive filenames are not reliable version metadata; explicit `--version` is the stable fallback.
- Next: run focused release CLI verification.

## Iteration 9

- Planned: fix runtime extraction failure on source archives containing repository symlinks.
- Implemented:
  - Changed ZIP extraction to allow relative symlinks whose resolved targets stay inside the extracted source tree.
  - Kept rejecting absolute, Windows-drive, backslash, escaping, dangling, cyclic, and path-colliding symlinks.
  - Extract regular files/directories first and create validated symlinks last.
  - Updated the spec from "reject symlinks" to "reject unsafe symlinks".
  - Added updater tests for internal symlinks, subdirectory symlinks, unsafe targets, dangling/cyclic targets, and child entries beneath symlinks.
- Learned:
  - Git provider source archives can legitimately contain symlink entries, so rejecting every symlink blocks valid repositories.
  - The security boundary should be whether a symlink can resolve outside the extracted app tree, not whether the archive uses symlinks at all.
- Next: retest the packaged launcher against the real release archive.

## Iteration 10

- Planned: make launcher rebuilds pick up source changes after the packaged app still showed old extraction behavior.
- Implemented:
  - Added `--clean` and `--noconfirm` to the PyInstaller invocation used by `launcher build`.
  - Added a build CLI test asserting that PyInstaller is run in clean, non-interactive mode.
- Learned:
  - Rebuilding a launcher package must not rely on PyInstaller's analysis cache when the Launcher library itself changed.
- Next: rebuild the app launcher and retry the same release update.

## Iteration 11

- Planned: reproduce the app-repo build/run and diagnose the repeated symlink error.
- Implemented:
  - Rebuilt the app launcher from the app repo with clean PyInstaller output.
  - Confirmed the packaged launcher now uses the new symlink policy and rejects the release archive because it contains an absolute symlink target.
  - Inspected the signed source archive and confirmed the problematic entry is an absolute home-directory symlink.
  - Fixed a Tkinter GUI crash that happened after showing the update error when the root window was destroyed during `update()`.
  - Added a Tkinter regression test that covers root destruction during event processing.
- Learned:
  - The remaining update failure is caused by non-portable app release archive content, not by a stale launcher build.
  - Runtime errors can destroy the Tk root while `_process_events_once` is still evaluating it.
- Next: remove the absolute symlink from the app release archive or replace it with portable app-data handling.

## Iteration 12

- Planned: catch runtime archive extraction failures during release signing and verification.
- Implemented:
  - Moved ZIP archive safety validation into a shared `launcher.archive_validation` module.
  - Updated runtime extraction and release CLI sign/verify to use the same validation rules.
  - Made `launcher release sign` reject unsafe release archives before writing signed metadata.
  - Made `launcher release verify` repeat archive safety validation before upload.
  - Narrowed release archive inference to `.zip`, matching the runtime extractor.
  - Updated packaging and security docs to describe ZIP-only release archives and sign/verify archive safety checks.
  - Added release CLI tests for unsafe symlink rejection and unsupported tar archive inference.
- Learned:
  - `upload` inherits the safety check through `verify`, so no extra upload-specific validation path is needed.
  - Archive validation belongs in a dependency-light module, not in updater network code.
- Next: re-run release signing on the app archive and expect the unsafe symlink failure before upload.

## Iteration 13

- Planned: improve developer-facing errors for missing release metadata and missing configured main scripts.
- Implemented:
  - Added explicit missing manifest/signature errors that point to `launcher release sign`, `verify`, and `upload`.
  - Added a clearer runtime error when `main` points to a file that is not present in the downloaded sources.
  - Added release CLI tests for missing manifest/signature guidance.
  - Added a runner test for missing configured main script guidance.
- Learned:
  - Missing release metadata is usually a skipped packaging step, so the error should show the normal command sequence.
  - Missing main script errors should explain both possible fixes: update config or include the file in the release archive.
- Next: use the clearer errors in the app packaging test cycle.

## Iteration 14

- Planned: explain the apparent "launcher stopped" behavior after the app process starts.
- Implemented:
  - Logged the launched application PID after `ScriptRunner.start`.
  - When no `init_message` is configured, logged that Launcher will exit and leave the app running.
  - Added a short post-start check that reports an error if the application exits immediately.
  - Included recent captured app output in the immediate-exit error when available.
  - Added runner and worker tests for startup handoff and immediate-exit detection.
- Learned:
  - Without `init_message`, returning to the shell is normal once Launcher starts the child process.
  - The handoff needs to be explicit in logs so success does not look like a silent stop.
- Next: rebuild the packaged launcher and retest the app handoff logs.

## Iteration 15

- Planned: make readiness verification optional and support apps whose runtime
  dependencies live in optional dependency groups.
- Implemented:
  - Added an `extras` config field and passed it to Wetlands as
    `optional_dependencies`.
  - Included `extras` in the dependency hash so changing optional groups
    recreates the runtime environment.
  - Added a clear configuration error when `extras` are configured but the
    dependency config file is missing from the downloaded sources.
  - Updated the init-timeout prompt to explain that reinstalling can fix a
    corrupted local environment but not a broken release.
  - Documented that `configuration` is relative to the downloaded repository
    root, that `extras` maps to optional dependency groups, and that
    `init_message` is optional.
- Learned:
  - Wetlands already supports optional dependency groups through
    `create_from_config(..., optional_dependencies=...)`, so no custom install
    command is needed for `uv sync --extra ...`-style projects.
  - A monorepo app commonly needs `configuration` to point at a subdirectory
    path such as `backend/pyproject.toml`, not the repository root.
  - A new review/explorer agent could not be started because the session had
    reached the agent thread limit.
- Next: run full test, lint, whitespace, and forbidden-example verification.

## Iteration 16

- Planned: make missing configured dependency files fail clearly.
- Implemented:
  - Changed `configuration` to support `null` as the explicit no-dependency-file
    mode.
  - Made a missing configured dependency file raise an environment error instead
    of silently creating an empty environment.
  - Kept omitted `configuration` defaulting to `pyproject.toml`.
  - Updated generated config comments, docs, specs, and tests for
    `configuration: null`.
- Learned:
  - The previous fallback was too permissive because it hid typos and monorepo
    path mistakes such as pointing at a root dependency file that is actually in
    a subdirectory.
- Next: commit the verified launcher packaging workflow changes.

## Iteration 17

- Planned: make launched source-layout apps import their own packages without
  requiring extra config for common monorepo layouts.
- Implemented:
  - Added `working_directory` and `pythonpath` config fields.
  - Inferred the launch working directory from the directory containing
    `configuration` when `working_directory` is not set.
  - Inferred `PYTHONPATH` from `working_directory/src` when present, plus the
    working directory itself.
  - Passed the launch cwd and merged `PYTHONPATH` through Wetlands subprocess
    options.
  - Documented inferred launch paths and explicit overrides in the packaging and
    configuration guides.
- Learned:
  - Running an absolute script inside a `src/` layout only puts the script's
    package directory on `sys.path`; the parent `src/` directory must be made
    importable separately.
- Next: run full lint, tests, whitespace, and example-string verification.
