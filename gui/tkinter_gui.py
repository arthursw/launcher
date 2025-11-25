"""Tkinter-based GUI implementation."""

import queue
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from typing import TYPE_CHECKING

from gui.base_gui import BaseGUI

if TYPE_CHECKING:
    from launcher import Launcher


class TkinterGUI(BaseGUI):
    """Tkinter-based GUI with progress bar and log display."""

    def __init__(self, launcher: "Launcher", event_queue: queue.Queue, response_queue: queue.Queue):
        """Initialize Tkinter GUI."""
        super().__init__(launcher, event_queue, response_queue)
        self.root = None
        self.log_text = None
        self.progress_var = None
        self.progress_bar = None
        self.should_close = False

    def show_proxy_dialog(self) -> dict:
        """Show proxy settings dialog using Tkinter.

        Returns:
            Dictionary with 'http' and 'https' proxy URLs
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("Proxy Configuration")
        dialog.geometry("400x200")
        dialog.resizable(False, False)

        ttk.Label(dialog, text="HTTP Proxy URL:").pack(pady=5)
        http_entry = ttk.Entry(dialog, width=40)
        http_entry.pack(pady=5)

        ttk.Label(dialog, text="HTTPS Proxy URL:").pack(pady=5)
        https_entry = ttk.Entry(dialog, width=40)
        https_entry.pack(pady=5)

        result = {"http": None, "https": None}

        def submit():
            result["http"] = http_entry.get() or None
            result["https"] = https_entry.get() or None
            dialog.destroy()

        ttk.Button(dialog, text="OK", command=submit).pack(pady=10)

        dialog.transient(self.root)
        dialog.grab_set()
        self.root.wait_window(dialog)

        return result

    def run(self) -> None:
        """Run Tkinter GUI."""
        self.root = tk.Tk()
        self.root.title("Application Launcher")
        self.root.geometry("600x400")

        # Create progress bar
        ttk.Label(self.root, text="Progress:").pack(pady=5)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.root,
            variable=self.progress_var,
            maximum=100,
            length=400,
        )
        self.progress_bar.pack(pady=5)

        # Create log text widget
        ttk.Label(self.root, text="Logs:").pack(pady=5)
        self.log_text = tk.Text(self.root, height=15, width=70)
        self.log_text.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        # Create scrollbar
        scrollbar = ttk.Scrollbar(self.log_text)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.log_text.yview)

        # Start monitoring events
        self._check_events()

        self.root.mainloop()

    def _check_events(self) -> None:
        """Check event queue for updates from worker thread."""
        if self.should_close:
            self.root.destroy()
            return

        try:
            event = self.event_queue.get_nowait()

            if event["type"] == "log":
                self.log_text.insert(tk.END, f"{event['message']}\n")
                self.log_text.see(tk.END)
                self.log_text.update()

            elif event["type"] == "progress":
                current = event.get("current", 0)
                total = event.get("total", 100)
                percentage = (current / total * 100) if total > 0 else 0
                self.progress_var.set(percentage)

            elif event["type"] == "error":
                messagebox.showerror("Error", event["message"])
                self.log_text.insert(tk.END, f"ERROR: {event['message']}\n")
                self.log_text.see(tk.END)

            elif event["type"] == "complete":
                if event.get("error"):
                    messagebox.showerror("Failed", "Launcher failed to complete")
                else:
                    messagebox.showinfo("Success", "Application launched successfully")
                self.should_close = True

            elif event["type"] == "proxy_required":
                proxy_settings = self.show_proxy_dialog()
                self.response_queue.put(
                    {
                        "type": "proxy_settings",
                        "request_id": event.get("request_id"),
                        "data": proxy_settings,
                    }
                )

        except queue.Empty:
            pass

        # Schedule next check
        self.root.after(100, self._check_events)
