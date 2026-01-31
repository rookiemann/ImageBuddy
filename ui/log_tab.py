# ui/log_tab.py
# Live log viewer tab

import tkinter as tk
from tkinter import ttk
from datetime import datetime
from core import logger
from core import theme


class LogTab:
    def __init__(self, parent):
        self.parent = parent
        self.log_entries = []
        self.auto_scroll = True
        self.filter_level = "ALL"
        self.max_entries = 500  # Default limit

        self._build_ui()
        self._start_log_polling()

    def _build_ui(self):
        """Build the log viewer interface."""
        # Top toolbar
        toolbar = ttk.Frame(self.parent, style="Main.TFrame")
        toolbar.pack(fill="x", padx=10, pady=10)

        ttk.Label(toolbar, text="Log Viewer", style="Heading.TLabel").pack(side="left")

        # Right side controls
        controls = ttk.Frame(toolbar, style="Main.TFrame")
        controls.pack(side="right")

        # Filter dropdown
        ttk.Label(controls, text="Filter:").pack(side="left", padx=(0, 5))
        self.filter_var = tk.StringVar(value="ALL")
        filter_combo = ttk.Combobox(controls, textvariable=self.filter_var,
                                     values=["ALL", "DEBUG", "INFO", "WARNING", "ERROR"],
                                     state="readonly", width=10)
        filter_combo.pack(side="left", padx=(0, 15))
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        # Max entries limit
        ttk.Label(controls, text="Max entries:").pack(side="left", padx=(0, 5))
        self.max_entries_var = tk.IntVar(value=self.max_entries)
        max_entries_spin = ttk.Spinbox(controls, from_=100, to=5000, increment=100,
                                        textvariable=self.max_entries_var, width=6)
        max_entries_spin.pack(side="left", padx=(0, 15))
        max_entries_spin.bind("<Return>", lambda e: self._update_max_entries())
        max_entries_spin.bind("<FocusOut>", lambda e: self._update_max_entries())

        # Auto-scroll checkbox
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="Auto-scroll", variable=self.auto_scroll_var,
                        command=self._toggle_auto_scroll).pack(side="left", padx=(0, 15))

        # Clear button
        ttk.Button(controls, text="Clear", style="Small.TButton",
                   command=self._clear_log).pack(side="left", padx=(0, 10))

        # Copy button
        ttk.Button(controls, text="Copy All", style="Small.TButton",
                   command=self._copy_log).pack(side="left")

        # Log text area with scrollbar
        log_frame = ttk.Frame(self.parent)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.log_text = tk.Text(
            log_frame,
            font=("Consolas", 10),
            background=theme.get_color("bg_input"),
            foreground=theme.get_color("text_primary"),
            insertbackground=theme.get_color("text_primary"),
            selectbackground=theme.get_color("accent"),
            selectforeground="white",
            wrap="word",
            state="disabled"
        )

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Configure text tags for log levels
        self.log_text.tag_configure("DEBUG", foreground="#6c757d")  # Gray
        self.log_text.tag_configure("INFO", foreground=theme.get_color("success"))  # Green
        self.log_text.tag_configure("WARNING", foreground="#ffc107")  # Yellow
        self.log_text.tag_configure("ERROR", foreground=theme.get_color("danger"))  # Red
        self.log_text.tag_configure("TIMESTAMP", foreground=theme.get_color("text_hint"))

        # Status bar
        status_frame = ttk.Frame(self.parent, style="Main.TFrame")
        status_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.status_var = tk.StringVar(value="0 log entries")
        ttk.Label(status_frame, textvariable=self.status_var, style="Hint.TLabel").pack(side="left")

        # Add initial message
        self._add_log_entry({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": "INFO",
            "message": "Log viewer started - watching for new log entries..."
        })

    def _start_log_polling(self):
        """Start polling for new log entries."""
        self._last_log_count = 0
        self._poll_logs()

    def _poll_logs(self):
        """Poll for new log entries from the logger buffer."""
        try:
            # Get current logs from logger
            current_logs = logger.get_log_buffer()
            new_count = len(current_logs)

            if new_count > self._last_log_count:
                # Add new entries
                for entry in current_logs[self._last_log_count:]:
                    self._add_log_entry(entry)
                self._last_log_count = new_count

        except Exception as e:
            pass  # Silently ignore polling errors

        # Schedule next poll
        self.parent.after(500, self._poll_logs)

    def _add_log_entry(self, entry: dict):
        """Add a log entry to the display."""
        level = entry.get("level", "INFO")
        timestamp = entry.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        message = entry.get("message", "")

        # Check filter
        if self.filter_level != "ALL" and level != self.filter_level:
            return

        self.log_entries.append(entry)

        # Format and add to text widget
        self.log_text.configure(state="normal")

        # Add timestamp
        self.log_text.insert("end", f"[{timestamp}] ", "TIMESTAMP")

        # Add level
        self.log_text.insert("end", f"[{level}] ", level)

        # Add message
        self.log_text.insert("end", f"{message}\n")

        self.log_text.configure(state="disabled")

        # Auto-scroll
        if self.auto_scroll_var.get():
            self.log_text.see("end")

        # Trim if over limit
        if len(self.log_entries) > self.max_entries:
            self._trim_log_entries()
        else:
            # Update status
            self.status_var.set(f"{len(self.log_entries)} log entries")

    def _apply_filter(self):
        """Apply log level filter."""
        self.filter_level = self.filter_var.get()

        # Clear and re-add all entries
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        # Get all logs and re-filter
        try:
            all_logs = logger.get_log_buffer()
            visible_count = 0

            for entry in all_logs:
                level = entry.get("level", "INFO")
                if self.filter_level == "ALL" or level == self.filter_level:
                    timestamp = entry.get("timestamp", "")
                    message = entry.get("message", "")

                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", f"[{timestamp}] ", "TIMESTAMP")
                    self.log_text.insert("end", f"[{level}] ", level)
                    self.log_text.insert("end", f"{message}\n")
                    self.log_text.configure(state="disabled")
                    visible_count += 1

            self.status_var.set(f"{visible_count} log entries (filtered)")

        except Exception:
            pass

    def _toggle_auto_scroll(self):
        """Toggle auto-scroll behavior."""
        self.auto_scroll = self.auto_scroll_var.get()

    def _update_max_entries(self):
        """Update max entries limit and trim if needed."""
        try:
            new_limit = self.max_entries_var.get()
            if new_limit < 100:
                new_limit = 100
                self.max_entries_var.set(100)
            self.max_entries = new_limit
            self._trim_log_entries()
        except:
            pass

    def _trim_log_entries(self):
        """Trim log entries to max limit."""
        if len(self.log_entries) > self.max_entries:
            # Keep only the most recent entries
            excess = len(self.log_entries) - self.max_entries
            self.log_entries = self.log_entries[excess:]

            # Rebuild display
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.configure(state="disabled")

            for entry in self.log_entries:
                level = entry.get("level", "INFO")
                if self.filter_level == "ALL" or level == self.filter_level:
                    timestamp = entry.get("timestamp", "")
                    message = entry.get("message", "")

                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", f"[{timestamp}] ", "TIMESTAMP")
                    self.log_text.insert("end", f"[{level}] ", level)
                    self.log_text.insert("end", f"{message}\n")
                    self.log_text.configure(state="disabled")

            if self.auto_scroll_var.get():
                self.log_text.see("end")

            self.status_var.set(f"{len(self.log_entries)} log entries (trimmed to {self.max_entries})")

    def _clear_log(self):
        """Clear the log display."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.log_entries.clear()
        self.status_var.set("0 log entries")
        logger.info("[LOG] Log viewer cleared")

    def _copy_log(self):
        """Copy all log text to clipboard."""
        self.log_text.configure(state="normal")
        content = self.log_text.get("1.0", "end-1c")
        self.log_text.configure(state="disabled")

        self.parent.clipboard_clear()
        self.parent.clipboard_append(content)

        self.status_var.set("Log copied to clipboard!")
        self.parent.after(2000, lambda: self.status_var.set(f"{len(self.log_entries)} log entries"))
