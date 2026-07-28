"""Main entry point for the launcher package."""

import argparse
import logging
import os
import queue
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from launcher.config import load_config
from launcher.gui.base import BaseGUI
from launcher.icons import runtime_icon_paths
from launcher.repository import default_release_asset_url_templates
from launcher.worker import EventType, LauncherWorker, create_queues

DEFAULT_CONFIG_NAME = "application.yml"
DEFAULT_PACKAGING_CONFIG = Path("packaging") / "launcher" / DEFAULT_CONFIG_NAME
CONFIG_ENV_VAR = "LAUNCHER_CONFIG"
DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
DEFAULT_SOURCE_ICON_NAME = "launcher.svg"
DEFAULT_PNG_ICON_NAME = "launcher.png"
INIT_ICON_NAMES = {
    ".icns": "app.icns",
    ".ico": "app.ico",
    ".png": "icon_128x128.png",
}


def setup_logging(debug: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_gui(
    gui_type: str,
    event_queue,
    response_queue,
    app_name: str,
    icon_paths: Sequence[Path] = (),
) -> BaseGUI:
    """Get the appropriate GUI instance."""
    if gui_type == "tkinter":
        from launcher.gui.tkinter_gui import TkinterGUI

        return TkinterGUI(event_queue, response_queue, app_name, icon_paths)
    if gui_type == "qt":
        from launcher.gui.qt_gui import QtGUI

        return QtGUI(event_queue, response_queue, app_name, icon_paths)
    if gui_type == "textual":
        from launcher.gui.textual_gui import TextualGUI

        return TextualGUI(event_queue, response_queue, app_name)
    if gui_type == "console":
        from launcher.gui.console_gui import ConsoleGUI

        return ConsoleGUI(event_queue, response_queue, app_name)
    raise ValueError(f"Unknown GUI type: {gui_type}")


def run_with_delayed_gui(
    worker: LauncherWorker,
    gui: BaseGUI,
    gui_timeout: float,
    event_queue,
) -> None:
    """Run the launcher while delaying GUI display until needed."""
    start_time = time.time()
    gui_shown = False
    pending_events = []

    worker.start()

    while worker.is_running() or not event_queue.empty():
        elapsed = time.time() - start_time

        if not gui_shown and elapsed >= gui_timeout:
            _restore_events(event_queue, pending_events)
            gui_shown = True
            gui.run()
            break

        try:
            event = event_queue.get(timeout=0.1 if worker.is_running() else 0)
            pending_events.append(event)

            if event.type == EventType.COMPLETE:
                _restore_events(event_queue, pending_events)
                break
            if event.type == EventType.ERROR:
                _restore_events(event_queue, pending_events)
                print(f"Error: {event.message}", file=sys.stderr)
                gui_shown = True
                gui.run()
                break
            if event.type == EventType.PROXY_REQUIRED:
                _restore_events(event_queue, pending_events)
                gui_shown = True
                gui.run()
                break
            if event.type in {
                EventType.INSTALL_LOCATION_REQUIRED,
                EventType.EXISTING_INSTALLATION,
                EventType.STATE_STORAGE_REQUIRED,
            }:
                _restore_events(event_queue, pending_events)
                gui_shown = True
                gui.run()
                break
        except queue.Empty:
            pass

    if not gui_shown:
        while worker.is_running():
            time.sleep(0.1)


def _restore_events(event_queue, events) -> None:
    """Put inspected events back for the GUI to consume."""
    while events:
        event_queue.put(events.pop(0))


def _unique_paths(paths: list[Path]) -> list[Path]:
    """Return paths without duplicates while preserving order."""
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _default_config_candidates() -> list[Path]:
    """Return default config locations in the order the launcher should check."""
    candidates = [Path.cwd() / DEFAULT_PACKAGING_CONFIG]

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        executable_dir = executable.parent
        bundle_dir = Path(__file__).resolve().parent
        internal_root = Path(getattr(sys, "_MEIPASS", bundle_dir.parent)).resolve()

        candidates.extend(
            [
                internal_root / DEFAULT_PACKAGING_CONFIG,
                executable_dir / DEFAULT_PACKAGING_CONFIG,
                bundle_dir / DEFAULT_PACKAGING_CONFIG,
            ]
        )
    else:
        repo_root = Path(__file__).resolve().parent.parent
        candidates.append(repo_root / DEFAULT_PACKAGING_CONFIG)

    return _unique_paths(candidates)


def find_config_path(config_path: Optional[Path] = None) -> tuple[Path, list[Path]]:
    """Find the configuration file to use."""
    if config_path is not None:
        return config_path.expanduser().resolve(), []

    env_config = os.environ.get(CONFIG_ENV_VAR)
    if env_config:
        return Path(env_config).expanduser().resolve(), []

    candidates = _default_config_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate, candidates

    return candidates[0], candidates


def run_launcher(argv: Sequence[str] | None = None, config_path: Optional[Path] = None) -> int:
    """Run the launcher runtime."""
    parser = argparse.ArgumentParser(
        description="Application launcher with auto-update",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help=f"Path to app config (default: {DEFAULT_PACKAGING_CONFIG})",
    )
    parser.add_argument(
        "--gui",
        "-g",
        choices=["tkinter", "qt", "textual", "console"],
        default="tkinter",
        help="GUI type to use (default: tkinter)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run without GUI (equivalent to --gui console)",
    )
    parser.add_argument(
        "--immediate-gui",
        action="store_true",
        help="Show GUI immediately instead of waiting for gui_timeout",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args(argv)
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)

    config_path, config_candidates = find_config_path(config_path or args.config)
    if not config_path.exists():
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        if config_candidates:
            checked = "\n  ".join(str(path) for path in config_candidates)
            print(f"Checked:\n  {checked}", file=sys.stderr)
        return 1

    try:
        config = load_config(config_path)
        app_name = config.name
        gui_timeout = config.gui_timeout if not args.immediate_gui else 0
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return 1

    gui_type = "console" if args.no_gui else args.gui
    event_queue, response_queue = create_queues()
    worker = LauncherWorker(config_path, event_queue, response_queue)

    try:
        gui = get_gui(gui_type, event_queue, response_queue, app_name, runtime_icon_paths(config_path))
    except ImportError as e:
        logger.error("Failed to import GUI: %s", e)
        print(
            f"Error: Failed to load {gui_type} GUI. Try a different --gui option.",
            file=sys.stderr,
        )
        return 1

    try:
        if gui_type in {"console", "textual"}:
            worker.start()
            gui.run()
        elif args.immediate_gui or gui_timeout == 0:
            worker.start()
            gui.run()
        else:
            run_with_delayed_gui(worker, gui, gui_timeout, event_queue)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        worker.stop()
        gui.destroy()

    if gui.error_message or worker.failed:
        return 1
    return 0


def check_config(argv: Sequence[str] | None = None, config_path: Optional[Path] = None) -> int:
    """Validate launcher configuration without starting the app."""
    parser = argparse.ArgumentParser(
        prog="launcher config check",
        description="Validate the launcher app configuration.",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help=f"Path to app config (default: {DEFAULT_PACKAGING_CONFIG})",
    )
    args = parser.parse_args(argv)

    resolved_path, config_candidates = find_config_path(config_path or args.config)
    if not resolved_path.exists():
        print(f"Error: Configuration file not found: {resolved_path}", file=sys.stderr)
        if config_candidates:
            checked = "\n  ".join(str(path) for path in config_candidates)
            print(f"Checked:\n  {checked}", file=sys.stderr)
        return 1

    try:
        load_config(resolved_path)
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return 1

    print(f"Configuration OK: {resolved_path}")
    return 0


def init_launcher(argv: Sequence[str] | None = None) -> int:
    """Create app-owned launcher packaging files."""
    parser = argparse.ArgumentParser(
        prog="launcher init",
        description="Create launcher packaging files for an app repository.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_PACKAGING_CONFIG)
    parser.add_argument("--name", default="MyApp", help="Application display name")
    parser.add_argument("--repository", default="https://github.com/my-org/myapp.git")
    parser.add_argument(
        "--mode",
        choices=["script", "module", "project"],
        default="script",
        help="App entrypoint mode",
    )
    parser.add_argument("--script", default="main.py", help="Python file for script mode")
    parser.add_argument("--module", default="my_app", help="Python module for module mode")
    parser.add_argument("--command", default="my-app", help="Installed command for project mode")
    parser.add_argument("--project-directory", default=None, help="Project directory for project mode")
    parser.add_argument("--arg", action="append", default=[], help="Argument passed to the app entrypoint")
    parser.add_argument("--path", default=".", help="Default root for sources and Python environments")
    parser.add_argument("--configuration", default="pyproject.toml", help="Dependency config inside app sources")
    parser.add_argument("--icon", type=Path, default=None, help="Custom launcher icon (.icns, .ico, or .png)")
    parser.add_argument("--force", action="store_true", help="Overwrite generated files if they already exist")
    args = parser.parse_args(argv)

    config_path = args.config.expanduser()
    icon_paths = _resolve_init_icons(args.icon, config_path.parent)
    if icon_paths is None:
        return 1

    write_paths = [config_path]
    write_paths.extend(destination for _source, destination in icon_paths)
    existing = [path for path in write_paths if path.exists()]
    if existing and not args.force:
        names = ", ".join(str(path) for path in existing)
        print(f"Error: launcher packaging file already exists: {names}", file=sys.stderr)
        print("Use --force to overwrite generated files.", file=sys.stderr)
        return 1

    config_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_url, signature_url, archive_url = _release_asset_urls(args.repository)
    config_lines = [
        f"name: {args.name}",
        f"repository: {args.repository}",
        "entrypoint:",
        f"  mode: {args.mode}",
    ]
    if args.mode == "script":
        config_lines.append(f"  script: {args.script}")
    elif args.mode == "module":
        config_lines.append(f"  module: {args.module}")
    else:
        config_lines.append(f"  command: {args.command}")
        if args.project_directory:
            config_lines.append(f"  project_directory: {args.project_directory}")
    if args.arg:
        config_lines.append("  args:")
        config_lines.extend(f"    - {arg}" for arg in args.arg)
    if args.path != ".":
        config_lines.append(f'path: "{args.path.format(name=args.name)}"')
    config_lines.extend(
        [
            "# Ask each user to confirm the runtime installation root on first launch.",
            "# Set to false to accept the resolved path default automatically.",
            "ask_install_location: true",
        ]
    )
    config_lines.extend(
        [
            "auto_update: true",
            "# The dependency config must exist in the downloaded sources. Use",
            "# configuration: null only when the app intentionally has no dependency file.",
            f"configuration: {args.configuration}",
            "# If the app needs optional Python dependencies, list their groups:",
            "# extras:",
            "#   - desktop",
            "# Launcher starts from the dependency config directory by default and",
            "# makes that directory, plus its src/ folder when present, importable.",
            "# Override only for unusual layouts:",
            "# working_directory: backend",
            "# pythonpath:",
            "#   - backend/src",
            "",
            "trust:",
            "  mode: signed_manifest",
            "  # Replace this with the public key printed by: launcher release keygen",
            '  public_key: "<base64-ed25519-public-key>"',
            "  # With repository set, Launcher infers these GitLab/GitHub release asset URLs.",
            "  # Uncomment only for custom hosting, custom asset paths, or renamed release assets.",
            f'  # manifest_url: "{manifest_url}"',
            f'  # signature_url: "{signature_url}"',
            f'  # archive_url: "{archive_url}"',
            "",
            "# No release.archive config is needed when tracked files are enough.",
            "# For generated assets, uncomment and adjust structured build/include config:",
            "# release:",
            "#   archive:",
            "#     build:",
            "#       - command: [\"npm\", \"ci\"]",
            "#         cwd: frontend",
            "#       - command: [\"npm\", \"run\", \"build\"]",
            "#         cwd: frontend",
            "#     include:",
            "#       - frontend/dist",
            "#       - source: frontend/dist",
            "#         destination: my_app/static",
            "# Rare full override fallback:",
            "#     custom_script: packaging/launcher/custom_archive.py",
            "",
        ]
    )
    config_path.write_text(
        "\n".join(config_lines)
    )
    for source_icon, icon_path in icon_paths:
        if source_icon.resolve() != icon_path.resolve():
            shutil.copy2(source_icon, icon_path)

    print(f"Created {config_path}")
    for _source_icon, icon_path in icon_paths:
        print(f"Created {icon_path}")
    return 0


def _resolve_init_icons(source: Path | None, packaging_dir: Path) -> list[tuple[Path, Path]] | None:
    if source is None:
        return _default_init_icons(packaging_dir)

    source = source.expanduser()
    if not source.is_file():
        print(f"Error: Icon file not found: {source}", file=sys.stderr)
        return None

    suffix = source.suffix.lower()
    icon_name = INIT_ICON_NAMES.get(suffix)
    if not icon_name:
        supported = ", ".join(sorted(INIT_ICON_NAMES))
        print(f"Error: Unsupported icon format: {source.suffix or source.name}. Expected one of: {supported}", file=sys.stderr)
        return None

    return [(source, packaging_dir / icon_name)]


def _default_init_icons(packaging_dir: Path) -> list[tuple[Path, Path]]:
    icons: list[tuple[Path, Path]] = []
    source_svg = DEFAULT_ASSETS_DIR / DEFAULT_SOURCE_ICON_NAME
    if source_svg.is_file():
        icons.append((source_svg, packaging_dir / DEFAULT_SOURCE_ICON_NAME))

    source_png = DEFAULT_ASSETS_DIR / DEFAULT_PNG_ICON_NAME
    if source_png.is_file():
        icons.append((source_png, packaging_dir / INIT_ICON_NAMES[".png"]))

    return icons


def main(argv: Sequence[str] | Path | None = None, config_path: Optional[Path] = None) -> int:
    """Main entry point for runtime and developer subcommands."""
    if isinstance(argv, Path):
        config_path = argv
        argv = None
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        command = args[0]
        rest = args[1:]
        if command == "run":
            return run_launcher(rest, config_path=config_path)
        if command == "release":
            from launcher import release_cli

            return release_cli.main(rest, prog="launcher release")
        if command == "init":
            return init_launcher(rest)
        if command == "build":
            from launcher import build_cli

            return build_cli.main(rest)
        if command == "config" and rest[:1] == ["check"]:
            return check_config(rest[1:], config_path=config_path)

    return run_launcher(args, config_path=config_path)


def _repo_name(repository: str) -> str:
    """Infer a repository name for generated trust URL placeholders."""
    cleaned = repository.rstrip("/").removesuffix(".git")
    if not cleaned:
        return "myapp"
    if ":" in cleaned and "/" not in cleaned.rsplit(":", 1)[0]:
        cleaned = cleaned.rsplit(":", 1)[1]
    return cleaned.rsplit("/", 1)[-1] or "myapp"


def _release_asset_urls(repository: str) -> tuple[str, str, str]:
    """Infer release asset URLs for generated config when possible."""
    try:
        templates = default_release_asset_url_templates(repository)
    except ValueError:
        base = f"https://github.com/my-org/{_repo_name(repository)}/releases/download/{{version}}"
        return (
            f"{base}/launcher-manifest.yml",
            f"{base}/launcher-manifest.yml.sig",
            f"{base}/{{archive_name}}",
        )

    return templates.manifest_url, templates.signature_url, templates.archive_url


if __name__ == "__main__":
    sys.exit(main())
