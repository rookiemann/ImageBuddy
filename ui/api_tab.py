# ui/api_tab.py
# API Server control tab with endpoint tester

import tkinter as tk
from tkinter import ttk
import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

from core import logger
from core import theme
from ui.ui_utils import add_tooltip, add_text_context_menu

CONFIG_FILE = Path(__file__).parent.parent / "config" / "settings.json"


class APITab:
    """API Server control and testing tab."""

    def __init__(self, parent, api_server):
        self.parent = parent
        self.api_server = api_server

        # Settings
        self.settings = self._load_settings()

        # Variables
        self.status_var = tk.StringVar(value="Stopped")
        self.uptime_var = tk.StringVar(value="--:--:--")
        self.url_var = tk.StringVar(value="")

        self.host_var = tk.StringVar(value=self.settings.get("api_host", "127.0.0.1"))
        self.port_var = tk.IntVar(value=self.settings.get("api_port", 5000))
        self.auto_start_var = tk.BooleanVar(value=self.settings.get("api_auto_start", False))
        self.cors_var = tk.BooleanVar(value=self.settings.get("api_cors_enabled", False))
        self.auto_load_vision_var = tk.BooleanVar(value=self.settings.get("api_auto_load_vision", True))
        self.auto_unload_vision_var = tk.BooleanVar(value=self.settings.get("api_auto_unload_vision", True))

        self.endpoint_var = tk.StringVar()
        self.response_time_var = tk.StringVar(value="")
        self.response_status_var = tk.StringVar(value="")

        # Build UI
        self._build_ui()

        # Start status polling
        self._poll_status()

    def _load_settings(self) -> dict:
        """Load settings from config file."""
        defaults = {
            "api_host": "127.0.0.1",
            "api_port": 5000,
            "api_auto_start": False,
            "api_cors_enabled": False,
            "api_auto_load_vision": True,
            "api_auto_unload_vision": True
        }
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    saved = json.load(f)
                    for key in defaults:
                        if key in saved:
                            defaults[key] = saved[key]
        except Exception as e:
            logger.error(f"[API Tab] Failed to load settings: {e}")
        return defaults

    def _save_settings(self):
        """Save settings to config file."""
        try:
            # Load existing settings
            existing = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    existing = json.load(f)

            # Update API settings
            existing["api_host"] = self.host_var.get()
            existing["api_port"] = self.port_var.get()
            existing["api_auto_start"] = self.auto_start_var.get()
            existing["api_cors_enabled"] = self.cors_var.get()
            existing["api_auto_load_vision"] = self.auto_load_vision_var.get()
            existing["api_auto_unload_vision"] = self.auto_unload_vision_var.get()

            # Save
            with open(CONFIG_FILE, "w") as f:
                json.dump(existing, f, indent=2)

            logger.info("[API Tab] Settings saved")
        except Exception as e:
            logger.error(f"[API Tab] Failed to save settings: {e}")

    def _build_ui(self):
        """Build the tab UI."""
        # Main scrollable container
        canvas = tk.Canvas(self.parent, highlightthickness=0, background=theme.get_color("bg_main"))
        scrollbar = ttk.Scrollbar(self.parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        self.container = ttk.Frame(canvas, style="Main.TFrame", padding=30)
        canvas.create_window((0, 0), window=self.container, anchor="nw")

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Mouse wheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(-int(event.delta / 120), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        row = 0

        # ========== SERVER STATUS SECTION ==========
        ttk.Label(self.container, text="API Server", style="Heading.TLabel").grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(0, 5))
        row += 1

        ttk.Label(self.container, text="Control the REST API for external access to ImageBuddy.",
                  style="Hint.TLabel").grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 20))
        row += 1

        # Status display
        status_frame = ttk.Frame(self.container)
        status_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 15))

        ttk.Label(status_frame, text="Status:").pack(side="left")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var,
                                       font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side="left", padx=(5, 20))

        ttk.Label(status_frame, text="Uptime:").pack(side="left")
        ttk.Label(status_frame, textvariable=self.uptime_var).pack(side="left", padx=(5, 20))

        ttk.Label(status_frame, text="URL:").pack(side="left")
        url_label = ttk.Label(status_frame, textvariable=self.url_var,
                              foreground=theme.get_color("accent"))
        url_label.pack(side="left", padx=(5, 0))
        row += 1

        # Control buttons
        btn_frame = ttk.Frame(self.container)
        btn_frame.grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 30))

        self.start_btn = ttk.Button(btn_frame, text="Start Server", style="Small.Primary.TButton",
                                     command=self._start_server, width=14)
        self.start_btn.pack(side="left", padx=(0, 10))

        self.stop_btn = ttk.Button(btn_frame, text="Stop Server", style="Small.Danger.TButton",
                                    command=self._stop_server, width=14, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 10))

        ttk.Button(btn_frame, text="Copy URL", style="Small.TButton",
                   command=self._copy_url, width=10).pack(side="left")
        row += 1

        # ========== CONFIGURATION SECTION ==========
        ttk.Separator(self.container, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=(0, 20))
        row += 1

        ttk.Label(self.container, text="Configuration", style="Subheading.TLabel").grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(0, 15))
        row += 1

        # Configuration grid with consistent label widths
        config_frame = ttk.Frame(self.container)
        config_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 15))
        config_frame.grid_columnconfigure(1, weight=0)
        config_frame.grid_columnconfigure(3, weight=1)

        # Row 0: Host and Port
        ttk.Label(config_frame, text="Host:", width=12, anchor="w").grid(
            row=0, column=0, sticky="w", pady=4)
        host_entry = ttk.Entry(config_frame, textvariable=self.host_var, width=15)
        host_entry.grid(row=0, column=1, sticky="w", padx=(0, 30), pady=4)

        ttk.Label(config_frame, text="Port:", width=8, anchor="w").grid(
            row=0, column=2, sticky="w", pady=4)
        ttk.Spinbox(config_frame, textvariable=self.port_var, from_=1024, to=65535, width=8).grid(
            row=0, column=3, sticky="w", pady=4)

        # Row 1: Server options
        ttk.Label(config_frame, text="Server:", width=12, anchor="w").grid(
            row=1, column=0, sticky="w", pady=4)
        server_opts = ttk.Frame(config_frame)
        server_opts.grid(row=1, column=1, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(server_opts, text="Auto-start on launch",
                        variable=self.auto_start_var).pack(side="left", padx=(0, 20))
        ttk.Checkbutton(server_opts, text="Enable CORS",
                        variable=self.cors_var).pack(side="left")

        # Row 2: Vision options
        ttk.Label(config_frame, text="Vision:", width=12, anchor="w").grid(
            row=2, column=0, sticky="w", pady=4)
        vision_opts = ttk.Frame(config_frame)
        vision_opts.grid(row=2, column=1, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(vision_opts, text="Auto-load on analyze",
                        variable=self.auto_load_vision_var).pack(side="left", padx=(0, 20))
        ttk.Checkbutton(vision_opts, text="Auto-unload after batch",
                        variable=self.auto_unload_vision_var).pack(side="left")
        row += 1

        # Save button
        ttk.Button(self.container, text="Save Configuration", style="Small.TButton",
                   command=self._save_settings, width=18).grid(row=row, column=0, sticky="w", pady=(0, 30))
        row += 1

        # ========== ENDPOINT TESTER SECTION ==========
        ttk.Separator(self.container, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=(0, 20))
        row += 1

        ttk.Label(self.container, text="Endpoint Tester", style="Subheading.TLabel").grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(0, 15))
        row += 1

        # Endpoint dropdown
        endpoint_frame = ttk.Frame(self.container)
        endpoint_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 10))

        ttk.Label(endpoint_frame, text="Endpoint:").pack(side="left")
        self.endpoint_combo = ttk.Combobox(endpoint_frame, textvariable=self.endpoint_var,
                                            state="readonly", width=50)
        self.endpoint_combo['values'] = self._get_endpoint_list()
        self.endpoint_combo.pack(side="left", padx=(5, 0))
        self.endpoint_combo.bind("<<ComboboxSelected>>", self._on_endpoint_change)
        if self.endpoint_combo['values']:
            self.endpoint_combo.current(0)
        row += 1

        # Parameters frame
        params_label_frame = ttk.LabelFrame(self.container, text="Parameters")
        params_label_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 10))

        self.params_frame = ttk.Frame(params_label_frame, padding=10)
        self.params_frame.pack(fill="x")

        self.param_entries = {}
        self._build_param_fields()
        row += 1

        # Request buttons
        req_btn_frame = ttk.Frame(self.container)
        req_btn_frame.grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 10))

        ttk.Button(req_btn_frame, text="Send Request", style="Small.Primary.TButton",
                   command=self._send_request, width=14).pack(side="left", padx=(0, 10))
        ttk.Button(req_btn_frame, text="Clear Response", style="Small.TButton",
                   command=self._clear_response, width=14).pack(side="left")

        # Response info
        response_info = ttk.Frame(req_btn_frame)
        response_info.pack(side="right")
        ttk.Label(response_info, textvariable=self.response_status_var).pack(side="left", padx=(0, 15))
        ttk.Label(response_info, textvariable=self.response_time_var).pack(side="left")
        row += 1

        # Response text area
        response_frame = ttk.LabelFrame(self.container, text="Response")
        response_frame.grid(row=row, column=0, columnspan=4, sticky="nsew", pady=(0, 10))

        self.response_text = tk.Text(
            response_frame,
            height=15,
            font=("Consolas", 10),
            background=theme.get_color("bg_input"),
            foreground=theme.get_color("text_primary"),
            insertbackground=theme.get_color("text_primary"),
            wrap="word"
        )
        self.response_text.pack(fill="both", expand=True, padx=5, pady=5)

        response_scroll = ttk.Scrollbar(self.response_text, orient="vertical", command=self.response_text.yview)
        self.response_text.configure(yscrollcommand=response_scroll.set)
        response_scroll.pack(side="right", fill="y")
        row += 1

        # Copy response button
        ttk.Button(self.container, text="Copy Response", style="Small.TButton",
                   command=self._copy_response, width=14).grid(row=row, column=0, sticky="w", pady=(0, 30))
        row += 1

        # ========== QUICK REFERENCE SECTION ==========
        ttk.Separator(self.container, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=(0, 20))
        row += 1

        ttk.Label(self.container, text="Quick Reference", style="Subheading.TLabel").grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(0, 10))
        row += 1

        ref_text = """
Endpoints:
  GET  /api/v1/status              - Health check
  GET  /api/v1/stats               - Image statistics
  GET  /api/v1/images              - List images (paginated)
  GET  /api/v1/images/{id}         - Get single image
  GET  /api/v1/images/{id}/file    - Serve original file
  GET  /api/v1/images/{id}/thumb   - Serve thumbnail
  DELETE /api/v1/images/{id}       - Delete image
  PUT  /api/v1/images/{id}         - Update metadata
  POST /api/v1/images/query        - Advanced filter query

  GET  /api/v1/search/pixabay      - Search Pixabay
  GET  /api/v1/search/pexels       - Search Pexels
  GET  /api/v1/search/unsplash     - Search Unsplash
  POST /api/v1/search              - Multi-source search

  POST /api/v1/download            - Download single URL
  POST /api/v1/download/batch      - Batch download (async)
  GET  /api/v1/tasks/{id}          - Check task status

  GET  /api/v1/vision/status       - Vision engine status
  POST /api/v1/vision/load         - Load vision instances
  POST /api/v1/vision/unload       - Unload all instances
  POST /api/v1/vision/analyze/{id} - Analyze single image
  POST /api/v1/vision/analyze      - Batch analyze (async)

Combo Endpoints (auto-load/unload vision):
  POST /api/v1/combo/search-download         - Search + download
  POST /api/v1/combo/download-analyze        - Download + analyze
  POST /api/v1/combo/analyze-unprocessed     - Analyze all unprocessed
  POST /api/v1/combo/smart-analyze           - Full workflow with auto-unload
  POST /api/v1/combo/search-download-analyze - Search + download + analyze
""".strip()

        ref_label = ttk.Label(self.container, text=ref_text, font=("Consolas", 9),
                              justify="left", foreground=theme.get_color("text_secondary"))
        ref_label.grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 20))

        # Configure grid weights
        self.container.grid_columnconfigure(0, weight=1)

        # Add context menus and tooltips
        self._add_ui_enhancements()

    def _add_ui_enhancements(self):
        """Add context menus and tooltips to UI elements."""
        # Add context menu to response text (readonly)
        add_text_context_menu(self.response_text, readonly=True)

        # Add tooltips
        add_tooltip(self.start_btn, "Start the REST API server")
        add_tooltip(self.stop_btn, "Stop the REST API server")

    def _get_endpoint_list(self):
        """Get list of available endpoints for dropdown."""
        return [
            "GET /api/v1/status",
            "GET /api/v1/stats",
            "GET /api/v1/images",
            "GET /api/v1/images/{id}",
            "GET /api/v1/images/{id}/file",
            "GET /api/v1/images/{id}/thumb",
            "DELETE /api/v1/images/{id}",
            "POST /api/v1/images/delete",
            "PUT /api/v1/images/{id}",
            "POST /api/v1/images/query",
            "GET /api/v1/search/pixabay",
            "GET /api/v1/search/pexels",
            "GET /api/v1/search/unsplash",
            "POST /api/v1/search",
            "POST /api/v1/download",
            "POST /api/v1/download/batch",
            "GET /api/v1/tasks/{id}",
            "GET /api/v1/vision/status",
            "POST /api/v1/vision/load",
            "POST /api/v1/vision/unload",
            "POST /api/v1/vision/analyze/{id}",
            "POST /api/v1/vision/analyze",
            "POST /api/v1/combo/search-download",
            "POST /api/v1/combo/download-analyze",
            "POST /api/v1/combo/analyze-unprocessed",
            "POST /api/v1/combo/smart-analyze",
            "POST /api/v1/combo/search-download-analyze"
        ]

    def _get_endpoint_params(self, endpoint: str) -> dict:
        """Get parameter definitions for an endpoint."""
        params = {
            "GET /api/v1/images": {
                "page": ("1", "Page number"),
                "per_page": ("50", "Items per page"),
                "source": ("", "Filter by source"),
            },
            "GET /api/v1/images/{id}": {
                "id": ("", "Image ID (required)")
            },
            "DELETE /api/v1/images/{id}": {
                "id": ("", "Image ID (required)")
            },
            "GET /api/v1/images/{id}/file": {
                "id": ("", "Image ID (required)")
            },
            "GET /api/v1/images/{id}/thumb": {
                "id": ("", "Image ID (required)")
            },
            "POST /api/v1/images/delete": {
                "ids": ("[]", "JSON array of IDs")
            },
            "PUT /api/v1/images/{id}": {
                "id": ("", "Image ID (required)"),
                "tags": ("[]", "JSON array of tags"),
                "alt": ("", "Caption/alt text")
            },
            "POST /api/v1/images/query": {
                "body": ('{"filters": {"source": []}, "pagination": {"page": 1, "per_page": 50}}', "JSON body")
            },
            "GET /api/v1/search/pixabay": {
                "query": ("", "Search query (required)"),
                "page": ("1", "Page number")
            },
            "GET /api/v1/search/pexels": {
                "query": ("", "Search query (required)"),
                "page": ("1", "Page number")
            },
            "GET /api/v1/search/unsplash": {
                "query": ("", "Search query (required)"),
                "page": ("1", "Page number")
            },
            "POST /api/v1/search": {
                "body": ('{"query": "", "sources": {"pixabay": 1, "pexels": 1, "unsplash": 1}}', "JSON body")
            },
            "POST /api/v1/download": {
                "body": ('{"url": "", "tags": [], "source": "API", "query": "download", "preview_only": false}', "JSON body")
            },
            "POST /api/v1/download/batch": {
                "body": ('{"items": [{"url": "", "tags": [], "source": "API"}], "preview_only": false}', "JSON body")
            },
            "GET /api/v1/tasks/{id}": {
                "id": ("", "Task ID (required)")
            },
            "POST /api/v1/vision/load": {
                "body": ('{"device": "auto", "count": 1}', "JSON body (device: auto/cpu/gpu/0/1)")
            },
            "POST /api/v1/vision/analyze/{id}": {
                "id": ("", "Image ID (required)"),
                "body": ('{"need_objects": true, "apply_to_db": true, "auto_load": true}', "JSON body")
            },
            "POST /api/v1/vision/analyze": {
                "body": ('{"ids": [], "need_objects": true, "auto_load": true}', "JSON body")
            },
            "POST /api/v1/combo/search-download": {
                "body": ('{"query": "", "sources": {"pixabay": 1}, "limit": 10, "preview_only": false}', "JSON body")
            },
            "POST /api/v1/combo/download-analyze": {
                "body": ('{"url": "", "tags": [], "source": "API", "query": "download", "auto_load": true}', "JSON body")
            },
            "POST /api/v1/combo/analyze-unprocessed": {
                "body": ('{"limit": 100, "sources": [], "auto_load": true}', "JSON body")
            },
            "POST /api/v1/combo/smart-analyze": {
                "body": ('{"ids": [], "sources": [], "limit": 100, "apply_captions": true, "apply_tags": true, "auto_unload": true}', "JSON body")
            },
            "POST /api/v1/combo/search-download-analyze": {
                "body": ('{"query": "", "sources": {"pixabay": 1}, "limit": 10, "auto_unload": true}', "JSON body")
            }
        }
        return params.get(endpoint, {})

    def _on_endpoint_change(self, event=None):
        """Handle endpoint selection change."""
        self._build_param_fields()

    def _build_param_fields(self):
        """Build parameter input fields for selected endpoint."""
        # Clear existing fields
        for widget in self.params_frame.winfo_children():
            widget.destroy()
        self.param_entries.clear()

        endpoint = self.endpoint_var.get()
        params = self._get_endpoint_params(endpoint)

        if not params:
            ttk.Label(self.params_frame, text="No parameters required",
                      foreground=theme.get_color("text_hint")).pack(anchor="w")
            return

        for i, (name, (default, hint)) in enumerate(params.items()):
            frame = ttk.Frame(self.params_frame)
            frame.pack(fill="x", pady=2)

            ttk.Label(frame, text=f"{name}:", width=10).pack(side="left")

            if name == "body":
                # Multi-line text for JSON body
                text = tk.Text(frame, height=4, width=60, font=("Consolas", 9),
                               background=theme.get_color("bg_input"),
                               foreground=theme.get_color("text_primary"))
                text.pack(side="left", padx=(5, 10))
                text.insert("1.0", default)
                self.param_entries[name] = text
            else:
                entry = ttk.Entry(frame, width=40)
                entry.pack(side="left", padx=(5, 10))
                entry.insert(0, default)
                self.param_entries[name] = entry

            ttk.Label(frame, text=hint, foreground=theme.get_color("text_hint")).pack(side="left")

    def _send_request(self):
        """Send API request."""
        if not self.api_server.is_running():
            self._show_response({"error": "Server not running"}, 0, 0)
            return

        endpoint = self.endpoint_var.get()
        if not endpoint:
            return

        parts = endpoint.split(" ", 1)
        method = parts[0]
        path = parts[1] if len(parts) > 1 else ""

        # Get parameters
        params = {}
        body = None

        for name, widget in self.param_entries.items():
            if name == "body":
                body = widget.get("1.0", "end").strip()
            elif name == "id":
                # Replace {id} in path
                value = widget.get().strip()
                path = path.replace("{id}", value)
            else:
                value = widget.get().strip()
                if value:
                    params[name] = value

        # Build URL
        base_url = f"http://{self.host_var.get()}:{self.port_var.get()}"
        url = base_url + path

        if params and method == "GET":
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url += "?" + query

        # Send request in thread
        def do_request():
            start_time = time.time()
            try:
                req = urllib.request.Request(url, method=method)
                req.add_header("Content-Type", "application/json")

                if body and method in ("POST", "PUT", "DELETE"):
                    req.data = body.encode("utf-8")

                with urllib.request.urlopen(req, timeout=120) as response:
                    elapsed = time.time() - start_time
                    data = response.read().decode("utf-8")
                    status = response.status

                    self.parent.after(0, lambda: self._show_response(
                        json.loads(data), status, elapsed * 1000
                    ))

            except urllib.error.HTTPError as e:
                elapsed = time.time() - start_time
                try:
                    data = e.read().decode("utf-8")
                    result = json.loads(data)
                except:
                    result = {"error": str(e)}

                self.parent.after(0, lambda: self._show_response(result, e.code, elapsed * 1000))

            except Exception as e:
                elapsed = time.time() - start_time
                self.parent.after(0, lambda: self._show_response(
                    {"error": str(e)}, 0, elapsed * 1000
                ))

        threading.Thread(target=do_request, daemon=True).start()

    def _show_response(self, data: dict, status: int, elapsed_ms: float):
        """Display response in text area."""
        self.response_text.delete("1.0", "end")
        self.response_text.insert("1.0", json.dumps(data, indent=2))

        if status >= 200 and status < 300:
            self.response_status_var.set(f"Status: {status} OK")
        elif status >= 400:
            self.response_status_var.set(f"Status: {status} Error")
        else:
            self.response_status_var.set(f"Status: {status}")

        self.response_time_var.set(f"Time: {elapsed_ms:.0f}ms")

    def _clear_response(self):
        """Clear response area."""
        self.response_text.delete("1.0", "end")
        self.response_status_var.set("")
        self.response_time_var.set("")

    def _copy_response(self):
        """Copy response to clipboard."""
        content = self.response_text.get("1.0", "end").strip()
        self.parent.clipboard_clear()
        self.parent.clipboard_append(content)

    def _copy_url(self):
        """Copy server URL to clipboard."""
        if self.api_server.is_running():
            url = self.api_server.get_url()
            self.parent.clipboard_clear()
            self.parent.clipboard_append(url)

    def _start_server(self):
        """Start the API server."""
        # Update server config
        self.api_server.host = self.host_var.get()
        self.api_server.port = self.port_var.get()

        if self.api_server.start():
            self._update_status()
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
        else:
            logger.error("[API Tab] Failed to start server")

    def _stop_server(self):
        """Stop the API server."""
        self.api_server.stop()
        self._update_status()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _update_status(self):
        """Update status display."""
        if self.api_server.is_running():
            self.status_var.set("Running")
            self.status_label.configure(foreground=theme.get_color("success"))
            self.url_var.set(self.api_server.get_url())

            # Calculate uptime
            if self.api_server.start_time:
                uptime = time.time() - self.api_server.start_time
                hours = int(uptime // 3600)
                minutes = int((uptime % 3600) // 60)
                seconds = int(uptime % 60)
                self.uptime_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.status_var.set("Stopped")
            self.status_label.configure(foreground=theme.get_color("danger"))
            self.url_var.set("")
            self.uptime_var.set("--:--:--")

    def _poll_status(self):
        """Poll server status periodically."""
        self._update_status()

        # Update button states
        if self.api_server.is_running():
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
        else:
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")

        # Schedule next poll
        self.parent.after(1000, self._poll_status)
