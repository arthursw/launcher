"""Tkinter GUI implementation for the launcher."""

import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from typing import Optional

from .base import BaseGUI
from ..worker import WorkerEvent, GUIResponse


class ProxyDialog(simpledialog.Dialog):
    """Dialog for entering proxy settings."""

    def __init__(self, parent, title: str = "Proxy Settings"):
        self.http_proxy: Optional[str] = None
        self.https_proxy: Optional[str] = None
        self.ssl_cert_file: Optional[str] = None
        super().__init__(parent, title)

    def body(self, master):
        """Create dialog body."""
        ttk.Label(master, text="HTTP Proxy:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.http_entry = ttk.Entry(master, width=40)
        self.http_entry.grid(row=0, column=1, padx=5, pady=5, columnspan=2)

        ttk.Label(master, text="HTTPS Proxy:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.https_entry = ttk.Entry(master, width=40)
        self.https_entry.grid(row=1, column=1, padx=5, pady=5, columnspan=2)

        ttk.Label(master, text="SSL Certificate:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.cert_entry = ttk.Entry(master, width=32)
        self.cert_entry.grid(row=2, column=1, padx=5, pady=5)
        ttk.Button(master, text="Browse...", command=self._browse_cert).grid(
            row=2, column=2, padx=5, pady=5
        )

        ttk.Label(
            master,
            text="Format: http://username:password@proxy.example.com:8080",
            font=("TkDefaultFont", 9, "italic"),
        ).grid(row=3, column=0, columnspan=3, pady=5)

        return self.http_entry

    def _browse_cert(self):
        """Open a file dialog to select a certificate file."""
        path = filedialog.askopenfilename(
            title="Select SSL Certificate",
            filetypes=[
                ("Certificate files", "*.pem *.crt *.cer"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.cert_entry.delete(0, tk.END)
            self.cert_entry.insert(0, path)

    def apply(self):
        """Handle OK button."""
        self.http_proxy = self.http_entry.get().strip() or None
        self.https_proxy = self.https_entry.get().strip() or None
        self.ssl_cert_file = self.cert_entry.get().strip() or None


class InitTimeoutDialog(simpledialog.Dialog):
    """Dialog for init timeout action."""

    def __init__(self, parent, message: str, title: str = "Initialization Timeout"):
        self.message = message
        self.action: str = "exit"
        super().__init__(parent, title)

    def body(self, master):
        """Create dialog body."""
        ttk.Label(master, text=self.message, wraplength=400).pack(padx=20, pady=10)
        ttk.Label(
            master,
            text="What would you like to do?",
        ).pack(padx=20, pady=5)
        return None

    def buttonbox(self):
        """Create custom buttons."""
        box = ttk.Frame(self)

        ttk.Button(box, text="Wait More", command=self._wait).pack(side="left", padx=5, pady=5)
        ttk.Button(box, text="Reinstall", command=self._reinstall).pack(side="left", padx=5, pady=5)
        ttk.Button(box, text="Exit", command=self._exit).pack(side="left", padx=5, pady=5)

        box.pack()

    def _wait(self):
        self.action = "wait"
        self.ok()

    def _reinstall(self):
        self.action = "reinstall"
        self.ok()

    def _exit(self):
        self.action = "exit"
        self.cancel()


class TkinterGUI(BaseGUI):
    """Tkinter-based GUI for the launcher."""

    def __init__(
        self,
        event_queue: queue.Queue[WorkerEvent],
        response_queue: queue.Queue[GUIResponse],
        app_name: str = "Launcher",
    ) -> None:
        super().__init__(event_queue, response_queue, app_name)
        self._root: Optional[tk.Tk] = None
        self._progress_bar: Optional[ttk.Progressbar] = None
        self._progress_label: Optional[ttk.Label] = None
        self._log_text: Optional[tk.Text] = None
        self._close_button: Optional[ttk.Button] = None

    def _create_window(self) -> None:
        """Create the main window."""
        self._root = tk.Tk()
        self._root.title(f"{self.app_name} - Launcher")
        self._root.geometry("600x400")
        self._root.minsize(400, 300)

        # Configure grid
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(2, weight=1)

        # Progress section
        progress_frame = ttk.Frame(self._root, padding="10")
        progress_frame.grid(row=0, column=0, sticky="ew")
        progress_frame.columnconfigure(0, weight=1)

        self._progress_label = ttk.Label(progress_frame, text="Starting...")
        self._progress_label.grid(row=0, column=0, sticky="w")

        self._progress_bar = ttk.Progressbar(
            progress_frame,
            mode="indeterminate",
            length=300,
        )
        self._progress_bar.grid(row=1, column=0, sticky="ew", pady=5)
        self._progress_bar.start(10)

        # Separator
        ttk.Separator(self._root, orient="horizontal").grid(row=1, column=0, sticky="ew")

        # Log section
        log_frame = ttk.Frame(self._root, padding="10")
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._log_text = tk.Text(
            log_frame,
            wrap="word",
            state="disabled",
            font=("Courier", 10),
        )
        self._log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._log_text.configure(yscrollcommand=scrollbar.set)

        # Button section
        button_frame = ttk.Frame(self._root, padding="10")
        button_frame.grid(row=3, column=0, sticky="ew")

        self._close_button = ttk.Button(
            button_frame,
            text="Close",
            command=self._on_close,
            state="disabled",
        )
        self._close_button.pack(side="right")

        # Handle window close
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _update_progress(self, current: int, total: int, message: str) -> None:
        """Update progress bar and label."""
        if not self._root:
            return

        if self._progress_label:
            self._progress_label.configure(text=message)

        if self._progress_bar:
            if total > 0:
                # Determinate progress
                self._progress_bar.stop()
                self._progress_bar.configure(mode="determinate", maximum=total, value=current)
            else:
                # Indeterminate progress
                if self._progress_bar.cget("mode") != "indeterminate":
                    self._progress_bar.configure(mode="indeterminate")
                    self._progress_bar.start(10)

    def _append_log(self, message: str) -> None:
        """Append message to log."""
        if not self._log_text:
            return

        self._log_text.configure(state="normal")
        self._log_text.insert("end", message + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _show_proxy_dialog(self, request_id: str) -> None:
        """Show proxy settings dialog."""
        if not self._root:
            return

        dialog = ProxyDialog(self._root)
        self._submit_proxy_response(
            request_id, dialog.http_proxy, dialog.https_proxy, dialog.ssl_cert_file
        )

    def _show_init_timeout_dialog(self, request_id: str, message: str) -> None:
        """Show init timeout dialog."""
        if not self._root:
            return

        dialog = InitTimeoutDialog(self._root, message)
        self._submit_init_timeout_response(request_id, dialog.action)

    def _show_error(self, message: str) -> None:
        """Show error message."""
        if self._progress_bar:
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate", value=0)

        if self._progress_label:
            self._progress_label.configure(text="Error occurred")

        if self._close_button:
            self._close_button.configure(state="normal")

        self._append_log(f"ERROR: {message}")

        if self._root:
            messagebox.showerror("Error", message, parent=self._root)

    def _show_complete(self) -> None:
        """Handle completion."""
        if self._progress_bar:
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate", value=100, maximum=100)

        if self._progress_label:
            self._progress_label.configure(text="Complete!")

        if self._close_button:
            self._close_button.configure(state="normal")

        self._append_log("Launcher complete. Application is running.")

    def _process_events_once(self) -> bool:
        """Process Tkinter events."""
        if not self._root:
            return False

        try:
            self._root.update()
            return self._root.winfo_exists()
        except tk.TclError:
            return False

    def _on_close(self) -> None:
        """Handle window close."""
        if self._root:
            self._root.destroy()
            self._root = None

    def show(self) -> None:
        """Show the window."""
        if self._root:
            self._root.deiconify()

    def hide(self) -> None:
        """Hide the window."""
        if self._root:
            self._root.withdraw()

    def destroy(self) -> None:
        """Destroy the GUI."""
        if self._root:
            self._root.destroy()
            self._root = None
