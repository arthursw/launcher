"""Main entry point for the launcher package."""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from launcher.config import load_config
from launcher.gui.base import BaseGUI
from launcher.worker import EventType, LauncherWorker, create_queues

DEFAULT_CONFIG_NAME = "application.yml"
DEFAULT_PACKAGING_CONFIG = Path("packaging") / "launcher" / DEFAULT_CONFIG_NAME
CONFIG_ENV_VAR = "LAUNCHER_CONFIG"
INIT_ICON_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x1f\xd4\x9d\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
) -> BaseGUI:
    """Get the appropriate GUI instance."""
    if gui_type == "tkinter":
        from launcher.gui.tkinter_gui import TkinterGUI

        return TkinterGUI(event_queue, response_queue, app_name)
    if gui_type == "qt":
        from launcher.gui.qt_gui import QtGUI

        return QtGUI(event_queue, response_queue, app_name)
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

    worker.start()

    while worker.is_running():
        elapsed = time.time() - start_time

        if not gui_shown and elapsed >= gui_timeout:
            gui_shown = True
            gui.run()
            break

        try:
            event = event_queue.get(timeout=0.1)
            event_queue.put(event)

            if event.type == EventType.COMPLETE:
                break
            if event.type == EventType.ERROR:
                print(f"Error: {event.message}", file=sys.stderr)
                break
            if event.type == EventType.PROXY_REQUIRED:
                gui_shown = True
                gui.run()
                break
        except Exception:
            pass

    if not gui_shown:
        while worker.is_running():
            time.sleep(0.1)


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
        gui = get_gui(gui_type, event_queue, response_queue, app_name)
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


def init_launcher(argv: Sequence[str] | None = None) -> int:
    """Create app-owned launcher packaging files."""
    parser = argparse.ArgumentParser(
        prog="launcher init",
        description="Create launcher packaging files for an app repository.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_PACKAGING_CONFIG)
    parser.add_argument("--name", default="MyApp", help="Application display name")
    parser.add_argument("--repository", default="https://github.com/my-org/myapp.git")
    parser.add_argument("--main", default="main.py", help="Main Python file inside downloaded app sources")
    parser.add_argument("--path", default="~/Applications/{name}", help="Install path for downloaded app sources")
    parser.add_argument("--configuration", default="pyproject.toml", help="Dependency config inside app sources")
    parser.add_argument("--force", action="store_true", help="Overwrite generated files if they already exist")
    args = parser.parse_args(argv)

    config_path = args.config.expanduser()
    icon_path = config_path.parent / "icon_128x128.png"
    existing = [path for path in (config_path, icon_path) if path.exists()]
    if existing and not args.force:
        names = ", ".join(str(path) for path in existing)
        print(f"Error: launcher packaging file already exists: {names}", file=sys.stderr)
        print("Use --force to overwrite generated files.", file=sys.stderr)
        return 1

    config_path.parent.mkdir(parents=True, exist_ok=True)
    install_path = args.path.format(name=args.name)
    manifest_url, signature_url = _release_asset_urls(args.repository)
    config_path.write_text(
        "\n".join(
            [
                f"name: {args.name}",
                f"repository: {args.repository}",
                f"main: {args.main}",
                f'path: "{install_path}"',
                "auto_update: true",
                f"configuration: {args.configuration}",
                "",
                "trust:",
                "  mode: signed_manifest",
                '  public_key: "<base64-ed25519-public-key>"',
                f'  manifest_url: "{manifest_url}"',
                f'  signature_url: "{signature_url}"',
                "",
            ]
        )
    )
    icon_path.write_bytes(INIT_ICON_BYTES)

    print(f"Created {config_path}")
    print(f"Created {icon_path}")
    return 0


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

    return run_launcher(args, config_path=config_path)


def _repo_name(repository: str) -> str:
    """Infer a repository name for generated trust URL placeholders."""
    cleaned = repository.rstrip("/").removesuffix(".git")
    if not cleaned:
        return "myapp"
    if ":" in cleaned and "/" not in cleaned.rsplit(":", 1)[0]:
        cleaned = cleaned.rsplit(":", 1)[1]
    return cleaned.rsplit("/", 1)[-1] or "myapp"


def _release_asset_urls(repository: str) -> tuple[str, str]:
    """Infer release asset URLs for generated config when possible."""
    cleaned = repository.rstrip("/").removesuffix(".git")
    owner_repo = ""
    if cleaned.startswith("https://github.com/"):
        owner_repo = cleaned.removeprefix("https://github.com/")
        base = f"https://github.com/{owner_repo}/releases/download/{{version}}"
    elif cleaned.startswith("git@github.com:"):
        owner_repo = cleaned.removeprefix("git@github.com:")
        base = f"https://github.com/{owner_repo}/releases/download/{{version}}"
    elif cleaned.startswith("https://gitlab.com/"):
        owner_repo = cleaned.removeprefix("https://gitlab.com/")
        base = f"https://gitlab.com/{owner_repo}/-/releases/{{version}}/downloads"
    elif cleaned.startswith("git@gitlab.com:"):
        owner_repo = cleaned.removeprefix("git@gitlab.com:")
        base = f"https://gitlab.com/{owner_repo}/-/releases/{{version}}/downloads"
    else:
        base = f"https://github.com/my-org/{_repo_name(repository)}/releases/download/{{version}}"

    return (
        f"{base}/launcher-manifest.yml",
        f"{base}/launcher-manifest.yml.sig",
    )


if __name__ == "__main__":
    sys.exit(main())
