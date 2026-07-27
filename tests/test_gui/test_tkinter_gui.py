"""Tests for the Tkinter GUI implementation."""

import queue
from pathlib import Path
from typing import Any, cast

from launcher.gui import tkinter_gui
from launcher.gui.tkinter_gui import TkinterGUI


def test_process_events_handles_root_destroyed_during_update():
    """Tk update callbacks may destroy the root before winfo_exists is checked."""
    gui = TkinterGUI(queue.Queue(), queue.Queue(), "TestApp")

    class RootDestroyedDuringUpdate:
        def update(self):
            gui._root = None

    gui._root = cast(Any, RootDestroyedDuringUpdate())

    assert gui._process_events_once() is False


def test_windows_applies_ico_as_default_window_icon(tmp_path, monkeypatch):
    """Windows should assign the native ICO to the Tk window and its dialogs."""
    icon = tmp_path / "app.ico"
    icon.write_bytes(b"ico")
    calls = []

    class Root:
        def iconbitmap(self, **kwargs):
            calls.append(kwargs)

    gui = TkinterGUI(queue.Queue(), queue.Queue(), "TestApp", [icon])
    gui._root = cast(Any, Root())
    monkeypatch.setattr(tkinter_gui.platform, "system", lambda: "Windows")

    gui._apply_window_icon()

    assert calls == [{"default": str(icon)}]


def test_tk_uses_png_fallback_and_keeps_image_reference(tmp_path, monkeypatch):
    """Tk should use a PNG on non-Windows platforms and retain the image object."""
    icon = tmp_path / "icon_128x128.png"
    icon.write_bytes(b"png")
    image = object()
    calls = []

    class Root:
        def iconphoto(self, default, photo):
            calls.append((default, photo))

    gui = TkinterGUI(queue.Queue(), queue.Queue(), "TestApp", [Path("app.icns"), icon])
    gui._root = cast(Any, Root())
    monkeypatch.setattr(tkinter_gui.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tkinter_gui.tk, "PhotoImage", lambda **kwargs: image)

    gui._apply_window_icon()

    assert calls == [(True, image)]
    assert gui._icon_image is image
