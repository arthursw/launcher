#!/usr/bin/env python3
"""Main entry point for the launcher application."""

import argparse
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from launcher.config import load_config
from launcher.worker import LauncherWorker, create_queues, EventType
from launcher.gui.base import BaseGUI


def setup_logging(debug: bool = False) -> None:
    """Set up logging configuration.

    Args:
        debug: If True, set log level to DEBUG
    """
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
    """Get the appropriate GUI instance.

    Args:
        gui_type: Type of GUI ('tkinter', 'qt', 'textual', 'console')
        event_queue: Event queue for worker communication
        response_queue: Response queue for worker communication
        app_name: Application name to display

    Returns:
        GUI instance

    Raises:
        ValueError: If gui_type is invalid
    """
    if gui_type == "tkinter":
        from launcher.gui.tkinter_gui import TkinterGUI
        return TkinterGUI(event_queue, response_queue, app_name)
    elif gui_type == "qt":
        from launcher.gui.qt_gui import QtGUI
        return QtGUI(event_queue, response_queue, app_name)
    elif gui_type == "textual":
        from launcher.gui.textual_gui import TextualGUI
        return TextualGUI(event_queue, response_queue, app_name)
    elif gui_type == "console":
        from launcher.gui.console_gui import ConsoleGUI
        return ConsoleGUI(event_queue, response_queue, app_name)
    else:
        raise ValueError(f"Unknown GUI type: {gui_type}")


def run_with_delayed_gui(
    worker: LauncherWorker,
    gui: BaseGUI,
    gui_timeout: float,
    event_queue,
) -> None:
    """Run the launcher with delayed GUI display.

    The GUI is only shown if the launcher takes longer than gui_timeout seconds.

    Args:
        worker: The launcher worker
        gui: The GUI instance
        gui_timeout: Seconds to wait before showing GUI
        event_queue: Event queue to monitor
    """
    start_time = time.time()
    gui_shown = False

    # Start the worker
    worker.start()

    # Monitor until complete or timeout
    while worker.is_running():
        elapsed = time.time() - start_time

        # Check if we should show GUI
        if not gui_shown and elapsed >= gui_timeout:
            gui_shown = True
            gui.run()
            break

        # Check for completion or error before timeout
        try:
            event = event_queue.get(timeout=0.1)
            # Put it back for the GUI to handle
            event_queue.put(event)

            if event.type == EventType.COMPLETE:
                # Completed before timeout, no need for GUI
                break
            elif event.type == EventType.ERROR:
                # Error before timeout, show error
                print(f"Error: {event.message}", file=sys.stderr)
                break
        except:
            pass

    # If GUI was shown, it will handle cleanup
    # Otherwise, wait for worker to finish
    if not gui_shown:
        while worker.is_running():
            time.sleep(0.1)


def main(config_path: Optional[Path] = None) -> int:
    """Main entry point.

    Args:
        config_path: Optional config file path. If provided, overrides CLI --config.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = argparse.ArgumentParser(
        description="Application launcher with auto-update",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=Path("application.yml"),
        help="Path to application.yml config file (default: application.yml)",
    )
    parser.add_argument(
        "--gui", "-g",
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

    # Setup logging
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)

    # Resolve config path (use parameter if provided, otherwise from CLI args)
    config_path = config_path.resolve() if config_path else args.config.resolve()
    assert config_path is not None, "Config path must be provided"
    if not config_path.exists():
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        return 1

    # Load config to get app name and gui_timeout
    try:
        config = load_config(config_path)
        app_name = config.name
        gui_timeout = config.gui_timeout if not args.immediate_gui else 0
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return 1

    # Determine GUI type
    gui_type = "console" if args.no_gui else args.gui

    # Create communication queues
    event_queue, response_queue = create_queues()

    # Create worker
    assert config_path is not None, "Config path must be provided"
    worker = LauncherWorker(config_path, event_queue, response_queue)

    # Create GUI
    try:
        gui = get_gui(gui_type, event_queue, response_queue, app_name)
    except ImportError as e:
        logger.error(f"Failed to import GUI: {e}")
        print(f"Error: Failed to load {gui_type} GUI. Try a different --gui option.", file=sys.stderr)
        return 1

    # Run with appropriate strategy
    try:
        if gui_type == "console" or gui_type == "textual":
            # Console and Textual handle their own event loops
            worker.start()
            gui.run()
        else:
            # Tkinter and Qt can have delayed GUI
            if args.immediate_gui or gui_timeout == 0:
                worker.start()
                gui.run()
            else:
                run_with_delayed_gui(worker, gui, gui_timeout, event_queue)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        worker.stop()
        gui.destroy()

    # Return appropriate exit code
    if gui.error_message:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
