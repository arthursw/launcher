"""Tests for the Tkinter GUI implementation."""

import queue

from launcher.gui.tkinter_gui import TkinterGUI


def test_process_events_handles_root_destroyed_during_update():
    """Tk update callbacks may destroy the root before winfo_exists is checked."""
    gui = TkinterGUI(queue.Queue(), queue.Queue(), "TestApp")

    class RootDestroyedDuringUpdate:
        def update(self):
            gui._root = None

    gui._root = RootDestroyedDuringUpdate()

    assert gui._process_events_once() is False
