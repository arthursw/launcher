"""Main entry point for the launcher package."""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from launcher.config import load_config
from launcher.gui.base import BaseGUI
from launcher.worker import EventType, LauncherWorker, create_queues

DEFAULT_CONFIG_NAME = "application.yml"
CONFIG_ENV_VAR = "LAUNCHER_CONFIG"


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
    candidates = [Path.cwd() / DEFAULT_CONFIG_NAME]

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        executable_dir = executable.parent
        app_name = executable.stem
        bundle_dir = Path(__file__).resolve().parent

        candidates.extend(
            [
                executable_dir / DEFAULT_CONFIG_NAME,
                executable_dir / f"{app_name}.yml",
                executable_dir / app_name / f"{app_name}.yml",
                bundle_dir / DEFAULT_CONFIG_NAME,
                bundle_dir / f"{app_name}.yml",
                bundle_dir / app_name / f"{app_name}.yml",
            ]
        )
    else:
        candidates.append(Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_NAME)

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


def main(config_path: Optional[Path] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Application launcher with auto-update",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Path to application.yml config file (default: application.yml)",
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

    args = parser.parse_args()
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


if __name__ == "__main__":
    sys.exit(main())
