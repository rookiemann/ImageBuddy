# ui/settings_tab.py
# Settings tab for API keys and configuration

import tkinter as tk
from tkinter import ttk
import json
import os
from pathlib import Path
from core import logger
from core import theme
from ui.ui_utils import add_tooltip, add_text_context_menu

CONFIG_FILE = Path(__file__).parent.parent / "config" / "settings.json"


class SettingsTab:
    def __init__(self, parent):
        self.parent = parent

        # Load current settings
        self.settings = self._load_settings()

        # Main scrollable container
        canvas = tk.Canvas(parent, highlightthickness=0, background=theme.get_color("bg_main"))
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
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

        self._build_ui()

    def _load_settings(self) -> dict:
        """Load settings from JSON file, falling back to config.py values."""
        defaults = {
            "pixabay_key": "",
            "pexels_key": "",
            "unsplash_key": "",
            "theme": "dark",
            # Florence-2 Vision settings
            "vision_auto_load": True,
            "vision_gpu_strategy": "auto",  # auto, all_gpus, single_best, specific, cpu_only
            "vision_gpu_enabled": {},  # {"0": True, "1": False} per GPU index
            "vision_gpu_instances": {},  # {"0": 2, "1": 4} per GPU index
            "vision_allow_cpu": None,  # None means "not set", will default based on GPU detection
            "vision_cpu_instances": 1,
            "vision_max_per_gpu": 4,
            "vision_max_total": 8,
            "vision_reserved_vram": 0.5,
            "vision_auto_unload": False,  # Unload instances after analysis completes
        }

        # Try to load from config.py first
        try:
            import config
            defaults["pixabay_key"] = getattr(config, "PIXABAY_KEY", "")
            defaults["pexels_key"] = getattr(config, "PEXELS_KEY", "")
            defaults["unsplash_key"] = getattr(config, "UNSPLASH_KEY", "")
        except ImportError:
            pass

        # Override with saved settings if they exist
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    saved = json.load(f)
                    defaults.update(saved)
        except Exception as e:
            logger.error(f"[SETTINGS] Failed to load settings: {e}")

        return defaults

    def _save_settings(self):
        """Save current settings to JSON file."""
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Build GPU enabled/instances dicts
            gpu_enabled = {}
            gpu_instances = {}
            for idx, (enabled_var, instances_var) in self.gpu_config_vars.items():
                gpu_enabled[str(idx)] = enabled_var.get()
                gpu_instances[str(idx)] = instances_var.get()

            settings = {
                "pixabay_key": self.pixabay_var.get().strip(),
                "pexels_key": self.pexels_var.get().strip(),
                "unsplash_key": self.unsplash_var.get().strip(),
                "theme": self.settings.get("theme", "dark"),  # Preserve existing theme
                # Vision settings
                "vision_auto_load": self.vision_auto_load_var.get(),
                "vision_gpu_strategy": self.vision_gpu_strategy_var.get(),
                "vision_gpu_enabled": gpu_enabled,
                "vision_gpu_instances": gpu_instances,
                "vision_allow_cpu": self.vision_allow_cpu_var.get(),
                "vision_cpu_instances": self.vision_cpu_instances_var.get(),
                "vision_max_per_gpu": self.vision_max_per_gpu_var.get(),
                "vision_max_total": self.vision_max_total_var.get(),
                "vision_reserved_vram": self.vision_reserved_vram_var.get(),
                "vision_auto_unload": self.vision_auto_unload_var.get(),
            }

            with open(CONFIG_FILE, "w") as f:
                json.dump(settings, f, indent=2)

            # Also update the config module in memory
            try:
                import config
                config.PIXABAY_KEY = settings["pixabay_key"]
                config.PEXELS_KEY = settings["pexels_key"]
                config.UNSPLASH_KEY = settings["unsplash_key"]
            except:
                pass

            logger.info("[SETTINGS] Settings saved successfully")
            self.status_var.set("Settings saved!")
            self.parent.after(3000, lambda: self.status_var.set(""))

        except Exception as e:
            logger.error(f"[SETTINGS] Failed to save settings: {e}")
            self.status_var.set(f"Error: {e}")

    def _build_ui(self):
        """Build the settings interface."""
        row = 0

        # Title
        ttk.Label(self.container, text="Settings", style="Heading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 30))
        row += 1

        # === API KEYS SECTION ===
        ttk.Label(self.container, text="API Keys", style="Subheading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 15))
        row += 1

        ttk.Label(self.container, text="Get free API keys from each service to enable image search.",
                  style="Hint.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 20))
        row += 1

        # Helper to open URLs in browser
        import webbrowser

        # Pixabay
        ttk.Label(self.container, text="Pixabay API Key:").grid(row=row, column=0, sticky="w", pady=8)
        pixabay_frame = ttk.Frame(self.container)
        pixabay_frame.grid(row=row, column=1, sticky="ew", padx=(15, 0), pady=8)
        self.pixabay_var = tk.StringVar(value=self.settings.get("pixabay_key", ""))
        pixabay_entry = ttk.Entry(pixabay_frame, textvariable=self.pixabay_var, width=50, show="*")
        pixabay_entry.pack(side="left", fill="x", expand=True)
        add_text_context_menu(pixabay_entry)
        ttk.Button(pixabay_frame, text="Get Key", style="Small.TButton", width=8,
                   command=lambda: webbrowser.open("https://pixabay.com/api/docs/")).pack(side="left", padx=(10, 0))
        row += 1

        # Pexels
        ttk.Label(self.container, text="Pexels API Key:").grid(row=row, column=0, sticky="w", pady=8)
        pexels_frame = ttk.Frame(self.container)
        pexels_frame.grid(row=row, column=1, sticky="ew", padx=(15, 0), pady=8)
        self.pexels_var = tk.StringVar(value=self.settings.get("pexels_key", ""))
        pexels_entry = ttk.Entry(pexels_frame, textvariable=self.pexels_var, width=50, show="*")
        pexels_entry.pack(side="left", fill="x", expand=True)
        add_text_context_menu(pexels_entry)
        ttk.Button(pexels_frame, text="Get Key", style="Small.TButton", width=8,
                   command=lambda: webbrowser.open("https://www.pexels.com/api/")).pack(side="left", padx=(10, 0))
        row += 1

        # Unsplash
        ttk.Label(self.container, text="Unsplash API Key:").grid(row=row, column=0, sticky="w", pady=8)
        unsplash_frame = ttk.Frame(self.container)
        unsplash_frame.grid(row=row, column=1, sticky="ew", padx=(15, 0), pady=8)
        self.unsplash_var = tk.StringVar(value=self.settings.get("unsplash_key", ""))
        unsplash_entry = ttk.Entry(unsplash_frame, textvariable=self.unsplash_var, width=50, show="*")
        unsplash_entry.pack(side="left", fill="x", expand=True)
        add_text_context_menu(unsplash_entry)
        ttk.Button(unsplash_frame, text="Get Key", style="Small.TButton", width=8,
                   command=lambda: webbrowser.open("https://unsplash.com/developers")).pack(side="left", padx=(10, 0))

        # Show/Hide keys toggle
        self.show_keys_var = tk.BooleanVar(value=False)
        def toggle_key_visibility():
            show = "*" if not self.show_keys_var.get() else ""
            pixabay_entry.configure(show=show)
            pexels_entry.configure(show=show)
            unsplash_entry.configure(show=show)

        ttk.Checkbutton(self.container, text="Show API keys", variable=self.show_keys_var,
                        command=toggle_key_visibility).grid(row=row, column=1, sticky="w", padx=(15, 0), pady=(10, 0))
        row += 1

        # Separator
        ttk.Separator(self.container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=30)
        row += 1

        # === TEST API KEYS ===
        ttk.Label(self.container, text="Test API Connections", style="Subheading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 15))
        row += 1

        test_frame = ttk.Frame(self.container)
        test_frame.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Button(test_frame, text="Test Pixabay", style="Small.TButton",
                   command=lambda: self._test_api("pixabay")).pack(side="left", padx=(0, 10))
        ttk.Button(test_frame, text="Test Pexels", style="Small.TButton",
                   command=lambda: self._test_api("pexels")).pack(side="left", padx=(0, 10))
        ttk.Button(test_frame, text="Test Unsplash", style="Small.TButton",
                   command=lambda: self._test_api("unsplash")).pack(side="left", padx=(0, 10))
        ttk.Button(test_frame, text="Test All", style="Small.Primary.TButton",
                   command=self._test_all_apis).pack(side="left", padx=(20, 0))
        row += 1

        self.test_result_var = tk.StringVar(value="")
        ttk.Label(self.container, textvariable=self.test_result_var, wraplength=500).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        row += 1

        # Separator
        ttk.Separator(self.container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=30)
        row += 1

        # === FLORENCE-2 VISION SETTINGS ===
        ttk.Label(self.container, text="Florence-2 Vision Engine", style="Subheading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 15))
        row += 1

        ttk.Label(self.container, text="Configure how Florence-2 loads for image analysis.",
                  style="Hint.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 20))
        row += 1

        # Auto-load on Analyze
        self.vision_auto_load_var = tk.BooleanVar(value=self.settings.get("vision_auto_load", True))
        ttk.Checkbutton(self.container, text="Auto-load when clicking Analyze (if no instances loaded)",
                        variable=self.vision_auto_load_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        row += 1

        # Auto-unload after Analysis
        self.vision_auto_unload_var = tk.BooleanVar(value=self.settings.get("vision_auto_unload", False))
        ttk.Checkbutton(self.container, text="Auto-unload instances after analysis completes (frees VRAM)",
                        variable=self.vision_auto_unload_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        row += 1

        # GPU Strategy dropdown
        ttk.Label(self.container, text="GPU Strategy:").grid(row=row, column=0, sticky="w", pady=8)
        self.vision_gpu_strategy_var = tk.StringVar(value=self.settings.get("vision_gpu_strategy", "auto"))
        strategy_combo = ttk.Combobox(self.container, textvariable=self.vision_gpu_strategy_var,
                                       values=["auto", "all_gpus", "single_best", "specific", "cpu_only"],
                                       state="readonly", width=25)
        strategy_combo.grid(row=row, column=1, sticky="w", padx=(15, 0), pady=8)
        row += 1

        # Strategy descriptions
        strategy_hints = ttk.Frame(self.container)
        strategy_hints.grid(row=row, column=0, columnspan=2, sticky="w", padx=(15, 0), pady=(0, 10))
        ttk.Label(strategy_hints, text="auto = Smart detection  |  all_gpus = Use every GPU  |  single_best = Best GPU only",
                  style="Hint.TLabel").pack(anchor="w")
        ttk.Label(strategy_hints, text="specific = Manual GPU selection  |  cpu_only = Force CPU mode",
                  style="Hint.TLabel").pack(anchor="w")
        row += 1

        # GPU-specific configuration frame
        gpu_config_frame = ttk.LabelFrame(self.container, text="GPU Configuration", padding=10)
        gpu_config_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        row += 1

        # Detect GPUs and create config for each
        self.gpu_config_vars = {}  # {idx: (enabled_var, instances_var)}
        self._build_gpu_config(gpu_config_frame)

        # CPU Settings
        cpu_frame = ttk.LabelFrame(self.container, text="CPU Settings", padding=10)
        cpu_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        row += 1

        # Default CPU based on GPU availability: off if GPUs present, on if no GPUs
        from core import system_monitor
        gpu_count = system_monitor.get_gpu_count()

        # Check if user explicitly set this value (None means not set)
        saved_cpu = self.settings.get("vision_allow_cpu")
        if saved_cpu is None:
            # Not explicitly set - default based on GPU availability
            default_cpu = (gpu_count == 0)  # True only if no GPUs
        else:
            default_cpu = saved_cpu

        self.vision_allow_cpu_var = tk.BooleanVar(value=default_cpu)
        cpu_label = "Allow CPU fallback (slower, uses more system resources)" if gpu_count > 0 else "Use CPU (no GPU detected)"
        ttk.Checkbutton(cpu_frame, text=cpu_label,
                        variable=self.vision_allow_cpu_var).grid(row=0, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Label(cpu_frame, text="CPU Instances (max):").grid(row=1, column=0, sticky="w", pady=4)
        self.vision_cpu_instances_var = tk.IntVar(value=self.settings.get("vision_cpu_instances", 1))
        ttk.Spinbox(cpu_frame, from_=1, to=2, textvariable=self.vision_cpu_instances_var, width=8).grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=4)

        ttk.Label(cpu_frame, text="(CPU mode is slower - 1 instance recommended)",
                  style="Hint.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Advanced limits
        limits_frame = ttk.LabelFrame(self.container, text="Instance Limits", padding=10)
        limits_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        row += 1

        ttk.Label(limits_frame, text="Max total instances:").grid(row=0, column=0, sticky="w", pady=4)
        self.vision_max_total_var = tk.IntVar(value=self.settings.get("vision_max_total", 8))
        ttk.Spinbox(limits_frame, from_=1, to=16, textvariable=self.vision_max_total_var, width=8).grid(
            row=0, column=1, sticky="w", padx=(10, 0), pady=4)

        # Hidden var for compatibility (uses per-GPU spinners instead)
        self.vision_max_per_gpu_var = tk.IntVar(value=self.settings.get("vision_max_per_gpu", 4))

        ttk.Label(limits_frame, text="Reserved VRAM per GPU (GB):").grid(row=1, column=0, sticky="w", pady=4)
        self.vision_reserved_vram_var = tk.DoubleVar(value=self.settings.get("vision_reserved_vram", 0.5))
        ttk.Spinbox(limits_frame, from_=0.5, to=4.0, increment=0.5,
                    textvariable=self.vision_reserved_vram_var, width=8).grid(
            row=1, column=1, sticky="w", padx=(10, 0), pady=4)

        ttk.Label(limits_frame, text="(Each Florence-2 instance uses ~2GB VRAM)",
                  style="Hint.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Separator
        ttk.Separator(self.container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=30)
        row += 1

        # === SAVE BUTTON ===
        button_frame = ttk.Frame(self.container)
        button_frame.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 20))

        ttk.Button(button_frame, text="Save Settings", style="Primary.TButton",
                   command=self._save_settings).pack(side="left", padx=(0, 20))

        self.status_var = tk.StringVar(value="")
        ttk.Label(button_frame, textvariable=self.status_var,
                  foreground=theme.get_color("success")).pack(side="left")
        row += 1

        # Configure column weights
        self.container.grid_columnconfigure(1, weight=1)

    def _test_api(self, service: str):
        """Test a single API connection."""
        import threading

        self.test_result_var.set(f"Testing {service.capitalize()}...")

        def test():
            try:
                import aiohttp
                import asyncio

                async def do_test():
                    if service == "pixabay":
                        key = self.pixabay_var.get().strip()
                        if not key:
                            return False, "No API key set"
                        url = f"https://pixabay.com/api/?key={key}&q=test&per_page=3"
                    elif service == "pexels":
                        key = self.pexels_var.get().strip()
                        if not key:
                            return False, "No API key set"
                        url = "https://api.pexels.com/v1/search?query=test&per_page=3"
                    elif service == "unsplash":
                        key = self.unsplash_var.get().strip()
                        if not key:
                            return False, "No API key set"
                        url = f"https://api.unsplash.com/search/photos?query=test&per_page=3"

                    headers = {}
                    if service == "pexels":
                        headers["Authorization"] = key
                    elif service == "unsplash":
                        headers["Authorization"] = f"Client-ID {key}"

                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, headers=headers, timeout=10) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if service == "pixabay":
                                    count = len(data.get("hits", []))
                                elif service == "pexels":
                                    count = len(data.get("photos", []))
                                elif service == "unsplash":
                                    count = len(data.get("results", []))
                                return True, f"OK - found {count} test images"
                            elif resp.status == 401:
                                return False, "Invalid API key"
                            else:
                                return False, f"HTTP {resp.status}"

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                success, msg = loop.run_until_complete(do_test())
                loop.close()

                result = f"{service.capitalize()}: {msg}"
                color = theme.get_color("success") if success else theme.get_color("danger")

                self.parent.after(0, lambda: self._update_test_result(result, success))
                logger.info(f"[API TEST] {result}")

            except Exception as e:
                result = f"{service.capitalize()}: Error - {str(e)}"
                self.parent.after(0, lambda: self._update_test_result(result, False))
                logger.error(f"[API TEST] {result}")

        threading.Thread(target=test, daemon=True).start()

    def _test_all_apis(self):
        """Test all API connections."""
        self.test_result_var.set("Testing all APIs...")

        import threading

        def test_all():
            results = []

            for service in ["pixabay", "pexels", "unsplash"]:
                try:
                    import aiohttp
                    import asyncio

                    async def do_test(svc):
                        if svc == "pixabay":
                            key = self.pixabay_var.get().strip()
                            if not key:
                                return svc, False, "No key"
                            url = f"https://pixabay.com/api/?key={key}&q=test&per_page=3"
                            headers = {}
                        elif svc == "pexels":
                            key = self.pexels_var.get().strip()
                            if not key:
                                return svc, False, "No key"
                            url = "https://api.pexels.com/v1/search?query=test&per_page=3"
                            headers = {"Authorization": key}
                        elif svc == "unsplash":
                            key = self.unsplash_var.get().strip()
                            if not key:
                                return svc, False, "No key"
                            url = f"https://api.unsplash.com/search/photos?query=test&per_page=3"
                            headers = {"Authorization": f"Client-ID {key}"}

                        async with aiohttp.ClientSession() as session:
                            async with session.get(url, headers=headers, timeout=10) as resp:
                                if resp.status == 200:
                                    return svc, True, "OK"
                                elif resp.status == 401:
                                    return svc, False, "Invalid key"
                                else:
                                    return svc, False, f"HTTP {resp.status}"

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    svc, success, msg = loop.run_until_complete(do_test(service))
                    loop.close()
                    results.append((svc.capitalize(), success, msg))

                except Exception as e:
                    results.append((service.capitalize(), False, str(e)[:30]))

            # Format results
            lines = []
            for svc, success, msg in results:
                status = "OK" if success else "FAIL"
                lines.append(f"{svc}: {status} - {msg}")

            result_text = " | ".join(lines)
            all_ok = all(r[1] for r in results)

            self.parent.after(0, lambda: self._update_test_result(result_text, all_ok))
            logger.info(f"[API TEST ALL] {result_text}")

        threading.Thread(target=test_all, daemon=True).start()

    def _update_test_result(self, text: str, success: bool):
        """Update test result label."""
        self.test_result_var.set(text)

    def _build_gpu_config(self, parent):
        """Build per-GPU configuration widgets."""
        from core import system_monitor

        gpu_count = system_monitor.get_gpu_count()

        if gpu_count == 0:
            ttk.Label(parent, text="No NVIDIA GPUs detected. CPU mode will be used.",
                      style="Hint.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=4)
            return

        # Header
        ttk.Label(parent, text="Enable", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(parent, text="GPU", font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(0, 20))
        ttk.Label(parent, text="Instances", font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(0, 10))
        ttk.Label(parent, text="VRAM", font=("Segoe UI", 9, "bold")).grid(row=0, column=3, sticky="w")

        saved_enabled = self.settings.get("vision_gpu_enabled", {})
        saved_instances = self.settings.get("vision_gpu_instances", {})

        for i in range(gpu_count):
            stats = system_monitor.get_gpu_stats(i)
            if not stats:
                continue

            row = i + 1
            gpu_name = stats["name"]
            vram_total = stats["vram_total_gb"]
            vram_free = vram_total - stats["vram_used_gb"]

            # Shorten GPU name
            for prefix in ["NVIDIA GeForce ", "NVIDIA ", "GeForce ", "AMD Radeon "]:
                if gpu_name.startswith(prefix):
                    gpu_name = gpu_name[len(prefix):]
                    break

            # Enabled checkbox
            enabled_var = tk.BooleanVar(value=saved_enabled.get(str(i), True))
            ttk.Checkbutton(parent, variable=enabled_var).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)

            # GPU name
            ttk.Label(parent, text=f"GPU {i}: {gpu_name}").grid(row=row, column=1, sticky="w", padx=(0, 20), pady=4)

            # Instance count spinner
            # Default: calculate based on free VRAM
            default_instances = max(1, min(4, int((vram_free - 0.5) / 2.0)))
            instances_var = tk.IntVar(value=saved_instances.get(str(i), default_instances))
            ttk.Spinbox(parent, from_=1, to=8, textvariable=instances_var, width=6).grid(
                row=row, column=2, sticky="w", padx=(0, 10), pady=4)

            # VRAM info
            vram_text = f"{vram_free:.1f} / {vram_total:.1f} GB free"
            ttk.Label(parent, text=vram_text, style="Hint.TLabel").grid(row=row, column=3, sticky="w", pady=4)

            self.gpu_config_vars[i] = (enabled_var, instances_var)

        # Refresh button
        ttk.Button(parent, text="Refresh GPU Info", style="Small.TButton",
                   command=lambda: self._refresh_gpu_config(parent)).grid(
            row=gpu_count + 1, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _refresh_gpu_config(self, parent):
        """Refresh GPU configuration display."""
        # Clear existing widgets
        for widget in parent.winfo_children():
            widget.destroy()
        self.gpu_config_vars.clear()
        # Rebuild
        self._build_gpu_config(parent)
