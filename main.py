"""Main entry point for the launcher application."""

import argparse
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Type

from gui.base_gui import BaseGUI
from gui.console_gui import ConsoleGUI
from gui.tkinter_gui import TkinterGUI
from gui.qt_gui import QtGUI
from gui.textual_gui import TextualGUI
from worker import launcher_worker


def find_config(config_path: Optional[str] = None) -> str:
    """Find application.yml configuration file.

    Searches in this order:
    1. Provided config_path argument
    2. Current directory
    3. Directory of main.py executable

    Args:
        config_path: Optional explicit path to config file

    Returns:
        Path to configuration file

    Raises:
        FileNotFoundError: If configuration file cannot be found
    """
    if config_path:
        path = Path(config_path)
        if path.exists():
            return str(path)
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Check current directory
    current_dir = Path("application.yml")
    if current_dir.exists():
        return str(current_dir)

    # Check next to main.py
    script_dir = Path(__file__).parent / "application.yml"
    if script_dir.exists():
        return str(script_dir)

    raise FileNotFoundError(
        "Could not find application.yml in current directory or next to launcher"
    )


def get_gui_class(gui_name: Optional[str] = None) -> Type[BaseGUI]:
    """Get GUI class by name.

    Args:
        gui_name: Name of GUI ('console', 'tkinter', 'qt', 'textual')
                 If None, returns ConsoleGUI

    Returns:
        GUI class

    Raises:
        ValueError: If GUI name is not recognized
    """
    gui_map = {
        "console": ConsoleGUI,
        "tkinter": TkinterGUI,
        "qt": QtGUI,
        "textual": TextualGUI,
    }

    if gui_name is None:
        return ConsoleGUI

    gui_name_lower = gui_name.lower()
    if gui_name_lower not in gui_map:
        raise ValueError(
            f"Unknown GUI: {gui_name}. Choose from: {', '.join(gui_map.keys())}"
        )

    return gui_map[gui_name_lower]


def should_show_gui(config_path: str, timeout: int) -> bool:
    """Determine if GUI should be shown based on timeout.

    Args:
        config_path: Path to configuration file
        timeout: Timeout in seconds before showing GUI

    Returns:
        True if enough time has passed, False otherwise
    """
    return timeout > 0  # For now, simple check based on timeout


def main(
    gui_class: Optional[Type[BaseGUI]] = None,
    config_path: Optional[str] = None,
    path_override: Optional[str] = None,
    show_gui: Optional[bool] = None,
) -> int:
    """Main launcher entry point.

    Args:
        gui_class: GUI class to use. If None, uses ConsoleGUI
        config_path: Path to application.yml. If None, searches for it
        path_override: Path override for application sources directory
        show_gui: Whether to show GUI. If None, auto-detects based on timeout

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Find configuration
        config_file = find_config(config_path)

        # Get GUI class
        if gui_class is None:
            gui_class = ConsoleGUI

        # Create communication queues
        event_queue = queue.Queue()
        response_queue = queue.Queue()

        # Create GUI instance
        # Note: We need a temporary launcher for GUI initialization
        from launcher import Launcher
        launcher = Launcher(config_file, path_override=path_override)

        gui = gui_class(launcher, event_queue, response_queue)

        # Start worker thread
        worker_thread = threading.Thread(
            target=launcher_worker,
            args=(config_file, event_queue, response_queue, path_override),
            daemon=True,
        )
        worker_thread.start()

        # Run GUI (this blocks until complete)
        gui.run()

        # Wait for worker thread to finish
        worker_thread.join(timeout=10)

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Application launcher with auto-update support"
    )
    parser.add_argument(
        "--config",
        "-c",
        help="Path to application.yml configuration file",
    )
    parser.add_argument(
        "--path",
        "-p",
        help="Override path attribute from configuration for application sources",
    )
    parser.add_argument(
        "--gui",
        "-g",
        default="console",
        help="GUI to use: console, tkinter, qt, textual (default: console)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run without GUI (console output only)",
    )

    args = parser.parse_args()

    # Get GUI class
    gui_class = get_gui_class(args.gui if not args.no_gui else "console")

    # Run launcher
    exit_code = main(
        gui_class=gui_class,
        config_path=args.config,
        path_override=args.path,
    )
    sys.exit(exit_code)
