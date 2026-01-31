# ui/system_footer.py
# System resource monitor footer with color-coded progress bars

import tkinter as tk
from tkinter import ttk
import threading
from core import logger
from core import system_monitor
from core import theme


class SystemFooter:
    """
    Footer bar with system resource meters and shutdown button.
    """

    POLL_INTERVAL_MS = 1500  # Update every 1.5 seconds

    # Color thresholds
    COLOR_NORMAL = "#4CAF50"    # Green
    COLOR_WARNING = "#FF9800"   # Orange
    COLOR_CRITICAL = "#F44336"  # Red

    THRESHOLD_WARNING = 70
    THRESHOLD_CRITICAL = 90

    def __init__(self, parent, on_shutdown_callback=None, vision_registry=None):
        self.parent = parent
        self.on_shutdown_callback = on_shutdown_callback
        self.vision_registry = vision_registry

        self.frame = None
        self._polling = True

        # Meter widgets
        self.cpu_bar = None
        self.cpu_label = None
        self.ram_bar = None
        self.ram_label = None
        self.gpu_meters = []

        self._setup_styles()
        self._build()
        self._start_polling()

    def _setup_styles(self):
        """Configure custom progressbar styles."""
        style = ttk.Style()

        trough = theme.get_color("scrollbar_bg")
        border = theme.get_color("border")
        thickness = 12

        style.configure("Green.Horizontal.TProgressbar",
                        background=self.COLOR_NORMAL,
                        troughcolor=trough,
                        thickness=thickness,
                        bordercolor=border,
                        lightcolor=self.COLOR_NORMAL,
                        darkcolor="#388E3C")

        style.configure("Orange.Horizontal.TProgressbar",
                        background=self.COLOR_WARNING,
                        troughcolor=trough,
                        thickness=thickness,
                        bordercolor=border,
                        lightcolor=self.COLOR_WARNING,
                        darkcolor="#F57C00")

        style.configure("Red.Horizontal.TProgressbar",
                        background=self.COLOR_CRITICAL,
                        troughcolor=trough,
                        thickness=thickness,
                        bordercolor=border,
                        lightcolor=self.COLOR_CRITICAL,
                        darkcolor="#D32F2F")

    def _get_bar_style(self, value: float) -> str:
        """Return appropriate style based on value."""
        if value >= self.THRESHOLD_CRITICAL:
            return "Red.Horizontal.TProgressbar"
        elif value >= self.THRESHOLD_WARNING:
            return "Orange.Horizontal.TProgressbar"
        return "Green.Horizontal.TProgressbar"

    def _get_label_color(self, value: float) -> str:
        """Return appropriate label color based on value."""
        if value >= self.THRESHOLD_CRITICAL:
            return self.COLOR_CRITICAL
        elif value >= self.THRESHOLD_WARNING:
            return self.COLOR_WARNING
        return theme.get_color("text_primary")

    def _build(self):
        """Build the footer UI."""
        self.frame = ttk.Frame(self.parent, style="Sidebar.TFrame")
        self.frame.pack(fill="x", side="bottom")

        inner = ttk.Frame(self.frame, style="Sidebar.TFrame")
        inner.pack(fill="x", padx=10, pady=6)

        col = 0

        # CPU meter
        cpu_frame = ttk.Frame(inner, style="Sidebar.TFrame")
        cpu_frame.grid(row=0, column=col, padx=(0, 15))
        col += 1

        ttk.Label(cpu_frame, text="CPU", font=("Segoe UI", 9),
                  foreground=theme.get_color("text_secondary"),
                  background=theme.get_color("bg_sidebar")).pack(side="left", padx=(0, 6))
        self.cpu_bar = ttk.Progressbar(cpu_frame, length=70, maximum=100,
                                        mode="determinate", style="Green.Horizontal.TProgressbar")
        self.cpu_bar.pack(side="left")
        self.cpu_label = ttk.Label(cpu_frame, text="0%", font=("Segoe UI", 9, "bold"),
                                    width=4, background=theme.get_color("bg_sidebar"))
        self.cpu_label.pack(side="left", padx=(6, 0))

        # RAM meter
        ram_frame = ttk.Frame(inner, style="Sidebar.TFrame")
        ram_frame.grid(row=0, column=col, padx=(0, 15))
        col += 1

        ttk.Label(ram_frame, text="RAM", font=("Segoe UI", 9),
                  foreground=theme.get_color("text_secondary"),
                  background=theme.get_color("bg_sidebar")).pack(side="left", padx=(0, 6))
        self.ram_bar = ttk.Progressbar(ram_frame, length=70, maximum=100,
                                        mode="determinate", style="Green.Horizontal.TProgressbar")
        self.ram_bar.pack(side="left")
        self.ram_label = ttk.Label(ram_frame, text="0%", font=("Segoe UI", 9, "bold"),
                                    width=4, background=theme.get_color("bg_sidebar"))
        self.ram_label.pack(side="left", padx=(6, 0))

        # GPU meters
        self._gpu_col_start = col
        self._build_gpu_meters(inner)
        col = self._gpu_col_start + len(self.gpu_meters)

        # Spacer
        spacer = ttk.Frame(inner, style="Sidebar.TFrame")
        spacer.grid(row=0, column=col, sticky="ew")
        inner.grid_columnconfigure(col, weight=1)
        col += 1

        # Theme toggle button
        theme_icon = "\u2600" if theme.is_dark() else "\u263d"
        theme_text = f"{theme_icon} Light" if theme.is_dark() else f"{theme_icon} Dark"
        self.theme_button = ttk.Button(
            inner,
            text=theme_text,
            style="Small.TButton",
            width=8,
            command=self._on_theme_toggle
        )
        self.theme_button.grid(row=0, column=col, sticky="e", padx=(8, 0))
        col += 1

        # Shutdown button
        ttk.Button(
            inner,
            text="Shutdown",
            style="Small.Danger.TButton",
            width=10,
            command=self._on_shutdown
        ).grid(row=0, column=col, sticky="e", padx=(8, 0))

    def _build_gpu_meters(self, parent):
        """Build GPU meter widgets."""
        gpu_count = system_monitor.get_gpu_count()
        col = self._gpu_col_start

        for i in range(gpu_count):
            stats = system_monitor.get_gpu_stats(i)
            if stats is None:
                continue

            gpu_frame = ttk.Frame(parent, style="Sidebar.TFrame")
            gpu_frame.grid(row=0, column=col, padx=(0, 15))
            col += 1

            # Shorten GPU name
            name = stats["name"]
            for prefix in ["NVIDIA GeForce ", "NVIDIA ", "GeForce ", "AMD Radeon "]:
                if name.startswith(prefix):
                    name = name[len(prefix):]
                    break
            short_name = name[:12] if len(name) > 12 else name

            ttk.Label(gpu_frame, text=short_name, font=("Segoe UI", 9),
                      foreground=theme.get_color("text_secondary"),
                      background=theme.get_color("bg_sidebar")).pack(side="left", padx=(0, 6))

            bar = ttk.Progressbar(gpu_frame, length=70, maximum=100,
                                   mode="determinate", style="Green.Horizontal.TProgressbar")
            bar.pack(side="left")

            pct_label = ttk.Label(gpu_frame, text="0%", font=("Segoe UI", 9, "bold"),
                                   width=4, background=theme.get_color("bg_sidebar"))
            pct_label.pack(side="left", padx=(6, 0))

            self.gpu_meters.append({
                "index": i,
                "bar": bar,
                "label": pct_label
            })

        if gpu_count == 0:
            # Show "No GPU" label
            no_gpu = ttk.Label(parent, text="No GPU", font=("Segoe UI", 9),
                               foreground=theme.get_color("text_hint"),
                               background=theme.get_color("bg_sidebar"))
            no_gpu.grid(row=0, column=col, padx=(0, 15))

    def _start_polling(self):
        """Start periodic stats update."""
        self._update_meters()

    def _update_meters(self):
        """Update all meter values."""
        if not self._polling:
            return

        try:
            stats = system_monitor.get_stats()

            # CPU
            cpu = stats["cpu"]
            self.cpu_bar["value"] = cpu
            self.cpu_bar.configure(style=self._get_bar_style(cpu))
            self.cpu_label.config(text=f"{cpu:.0f}%", foreground=self._get_label_color(cpu))

            # RAM
            ram = stats["ram"]
            self.ram_bar["value"] = ram
            self.ram_bar.configure(style=self._get_bar_style(ram))
            self.ram_label.config(text=f"{ram:.0f}%", foreground=self._get_label_color(ram))

            # GPUs (VRAM usage)
            for meter in self.gpu_meters:
                gpu_stats = system_monitor.get_gpu_stats(meter["index"])
                if gpu_stats:
                    vram = gpu_stats["vram_percent"]
                    meter["bar"]["value"] = vram
                    meter["bar"].configure(style=self._get_bar_style(vram))
                    meter["label"].config(text=f"{vram:.0f}%", foreground=self._get_label_color(vram))

        except Exception as e:
            logger.error(f"[Footer] Meter update error: {e}")

        if self._polling:
            self.parent.after(self.POLL_INTERVAL_MS, self._update_meters)

    def _on_shutdown(self):
        """Gracefully shutdown and quit."""
        logger.info("[Footer] Shutdown requested")
        self._polling = False

        def cleanup_and_quit():
            try:
                # Unload vision instances
                if self.vision_registry:
                    logger.info("[Footer] Unloading vision instances...")
                    self.vision_registry.unload_all()

                # Shutdown NVML
                system_monitor._shutdown_nvml()

                # Call extra callback if provided
                if self.on_shutdown_callback:
                    self.on_shutdown_callback()

            except Exception as e:
                logger.error(f"[Footer] Cleanup error: {e}")

            # Quit on main thread
            self.parent.after(0, self._force_quit)

        # Run cleanup in thread
        cleanup_thread = threading.Thread(target=cleanup_and_quit, daemon=False)
        cleanup_thread.start()

        # Force quit after timeout
        self.parent.after(5000, self._force_quit)

    def _force_quit(self):
        """Force quit the application."""
        try:
            self.parent.quit()
            self.parent.destroy()
        except:
            pass

    def _on_theme_toggle(self):
        """Toggle theme."""
        from tkinter import messagebox

        current = theme.get_theme_name()
        new_theme = "light" if current == "dark" else "dark"

        theme.set_theme(new_theme)

        # Update button
        theme_icon = "\u263d" if new_theme == "dark" else "\u2600"
        self.theme_button.config(text=f"{theme_icon} {new_theme.title()}")

        messagebox.showinfo(
            "Theme Changed",
            f"Theme changed to {new_theme.title()} mode.\n\nRestart the app for changes to take effect."
        )

    def stop_polling(self):
        """Stop the polling loop."""
        self._polling = False
