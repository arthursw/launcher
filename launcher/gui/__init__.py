"""GUI modules for the launcher application."""

from .base import BaseGUI

__all__ = ["BaseGUI", "TkinterGUI", "QtGUI", "TextualGUI", "ConsoleGUI"]


def __getattr__(name: str):
    """Import optional GUI backends only when they are requested."""
    if name == "TkinterGUI":
        from .tkinter_gui import TkinterGUI

        return TkinterGUI
    if name == "QtGUI":
        from .qt_gui import QtGUI

        return QtGUI
    if name == "TextualGUI":
        from .textual_gui import TextualGUI

        return TextualGUI
    if name == "ConsoleGUI":
        from .console_gui import ConsoleGUI

        return ConsoleGUI
    raise AttributeError(name)
