# app.py
# ImageBuddy - Stock Image Search, Download & AI Captioning

import sys
import os
import ctypes

# Fix import path for standalone run
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import json
from pathlib import Path

from core import logger
from core.theme import get_color, get_font, is_dark
from core.vision_registry import VisionRegistry
from core import system_monitor
from core.image_manager import ImageManager
import tkinter as tk
from tkinter import ttk

CONFIG_FILE = Path(__file__).parent / "config" / "settings.json"

os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"


def set_dark_title_bar(window):
    """Set dark title bar on Windows 10/11."""
    if sys.platform != 'win32':
        return

    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        if result != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception as e:
        logger.debug(f"Could not set dark title bar: {e}")


class ImageBuddyApp:
    def __init__(self):
        # Create window but keep it hidden until fully built
        self.root = tk.Tk()
        self.root.withdraw()  # Hide initially

        self.root.title("ImageBuddy")

        # Set size and position BEFORE showing
        width, height = 1200, 800
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1000, 600)

        # Set window icon (if exists)
        icon_ico = os.path.join(script_dir, "assets", "icon.ico")
        icon_png = os.path.join(script_dir, "assets", "icon.png")

        if os.path.exists(icon_ico):
            try:
                self.root.iconbitmap(icon_ico)
            except Exception as e:
                logger.debug(f"Could not set .ico icon: {e}")
        elif os.path.exists(icon_png):
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_png)
                photo = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, photo)
                self._icon_photo = photo
            except Exception as e:
                logger.debug(f"Could not set .png icon: {e}")

        # Vision registry (for Florence-2 instances)
        self.vision_registry = VisionRegistry()

        # Image manager singleton
        self.image_manager = ImageManager()

        # API Server (initialized but not started yet)
        self.api_server = None
        self._init_api_server()

        # Setup styles
        self._setup_styles()

        # Build main UI
        self._build_ui()

        # Handle window close button (X)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Now show the window
        self.root.deiconify()

        # Set dark title bar after window is shown
        if is_dark():
            self.root.after(50, lambda: set_dark_title_bar(self.root))

        logger.info("ImageBuddy started")

        # Log system info for debugging
        self._log_system_info()

        # Auto-start API server if configured
        self._auto_start_api()

    def _log_system_info(self):
        """Log system information for debugging support."""
        import platform

        logger.info("=" * 50)
        logger.info("SYSTEM INFORMATION")
        logger.info("=" * 50)
        logger.info(f"App Version: 1.0.0")
        logger.info(f"Python: {sys.version}")
        logger.info(f"Platform: {platform.system()} {platform.release()}")
        logger.info(f"Machine: {platform.machine()}")

        # GPU info
        try:
            gpu_count = system_monitor.get_gpu_count()
            if gpu_count > 0:
                logger.info(f"GPUs Detected: {gpu_count}")
                for i in range(gpu_count):
                    info = system_monitor.get_gpu_info(i)
                    if info:
                        logger.info(f"  GPU {i}: {info.get('name', 'Unknown')} - {info.get('memory_total', 0):.0f} MB VRAM")
            else:
                logger.info("GPUs Detected: None (CPU mode)")
        except Exception as e:
            logger.info(f"GPU Detection: Failed ({e})")

        # PyTorch info
        try:
            import torch
            logger.info(f"PyTorch: {torch.__version__}")
            logger.info(f"CUDA Available: {torch.cuda.is_available()}")
            if torch.cuda.is_available():
                logger.info(f"CUDA Version: {torch.version.cuda}")
        except ImportError:
            logger.info("PyTorch: Not installed")

        logger.info("=" * 50)

    def _init_api_server(self):
        """Initialize the API server."""
        try:
            from core.api_server import APIServer

            # Load settings
            settings = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    settings = json.load(f)

            host = settings.get("api_host", "127.0.0.1")
            port = settings.get("api_port", 5000)

            self.api_server = APIServer(
                self.image_manager,
                self.vision_registry,
                host=host,
                port=port
            )
            logger.info("[App] API Server initialized")
        except Exception as e:
            logger.error(f"[App] Failed to initialize API server: {e}")
            self.api_server = None

    def _auto_start_api(self):
        """Auto-start API server if configured."""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    settings = json.load(f)

                if settings.get("api_auto_start", False) and self.api_server:
                    logger.info("[App] Auto-starting API server...")
                    self.api_server.start()
        except Exception as e:
            logger.error(f"[App] Auto-start API error: {e}")

    def _setup_styles(self):
        """Setup ttk styles for the application."""
        style = ttk.Style()
        style.theme_use('classic')
        style.configure("TButton", takefocus=False)

        # Block canvas auto-scroll on focus
        def block_all_focus_scroll(event):
            w = event.widget
            while w:
                if isinstance(w, tk.Canvas):
                    return "break"
                w = w.master
            return None

        self.root.bind("<FocusIn>", block_all_focus_scroll)

        # Theme colors
        bg_main = get_color("bg_main")
        bg_card = get_color("bg_card")
        bg_sidebar = get_color("bg_sidebar")
        bg_input = get_color("bg_input")
        accent = get_color("accent")
        accent_dark = get_color("accent_dark")
        danger = get_color("danger")
        danger_dark = get_color("danger_dark")
        text_primary = get_color("text_primary")
        text_secondary = get_color("text_secondary")
        text_hint = get_color("text_hint")
        text_disabled = get_color("text_disabled")

        self.root.configure(bg=bg_main)

        # Fonts
        font_heading = get_font("heading")
        font_subheading = get_font("subheading")
        font_body = get_font("body")
        font_small = get_font("small")

        self.root.option_add("*Font", font_body)

        # Frames
        style.configure("Main.TFrame", background=bg_main)
        style.configure("Sidebar.TFrame", background=bg_sidebar)
        style.configure("Card.TFrame", background=bg_card, relief="flat", borderwidth=0)
        style.configure("Hover.Card.TFrame", background=get_color("bg_hover"))

        # Labels
        style.configure("TLabel", background=bg_main, foreground=text_primary)
        style.configure("Heading.TLabel", font=font_heading, foreground=text_primary, background=bg_main)
        style.configure("Subheading.TLabel", font=font_subheading, foreground=text_primary, background=bg_main)
        style.configure("Hint.TLabel", font=font_small, foreground=text_hint, background=bg_main)

        # Buttons
        style.configure("TButton",
                        font=font_body,
                        padding=6,
                        background=bg_sidebar,
                        foreground=text_primary)
        style.map("TButton",
                  background=[("active", get_color("bg_hover")), ("pressed", get_color("bg_hover"))],
                  foreground=[("disabled", text_disabled)])

        style.configure("Primary.TButton",
                        foreground="white", background=accent, font=font_subheading)
        style.map("Primary.TButton",
                  background=[("active", accent_dark), ("pressed", accent_dark)],
                  foreground=[("disabled", text_disabled)])

        style.configure("Danger.TButton",
                        foreground="white", background=danger, font=font_subheading)
        style.map("Danger.TButton",
                  background=[("active", danger_dark), ("pressed", danger_dark)],
                  foreground=[("disabled", text_disabled)])

        style.configure("Small.TButton",
                        font=font_body,
                        padding=[6, 3],
                        background=bg_sidebar,
                        foreground=text_primary)
        style.map("Small.TButton",
                  background=[("active", get_color("bg_hover")), ("pressed", get_color("bg_hover"))],
                  foreground=[("disabled", text_disabled)])

        style.configure("Small.Primary.TButton",
                        font=font_body,
                        padding=[6, 3],
                        foreground="white",
                        background=accent)
        style.map("Small.Primary.TButton",
                  background=[("active", accent_dark), ("pressed", accent_dark)],
                  foreground=[("disabled", text_disabled)])

        style.configure("Small.Danger.TButton",
                        font=font_body,
                        padding=[6, 3],
                        foreground="white",
                        background=danger)
        style.map("Small.Danger.TButton",
                  background=[("active", danger_dark), ("pressed", danger_dark)],
                  foreground=[("disabled", text_disabled)])

        # Notebook tabs
        style.configure("TNotebook", background=bg_main, borderwidth=0)
        style.configure("TNotebook.Tab",
                        padding=[20, 10],
                        font=font_subheading,
                        background=bg_sidebar,
                        foreground=text_secondary)
        style.map("TNotebook.Tab",
                  background=[("selected", bg_card), ("active", get_color("bg_hover"))],
                  foreground=[("selected", accent), ("!selected", text_primary)])

        # Entry / Input fields
        style.configure("TEntry",
                        fieldbackground=bg_input,
                        foreground=text_primary,
                        insertcolor=text_primary)

        # Spinbox
        style.configure("TSpinbox",
                        fieldbackground=bg_input,
                        foreground=text_primary,
                        insertcolor=text_primary,
                        arrowcolor=text_primary,
                        background=bg_sidebar)

        # Combobox
        style.configure("TCombobox",
                        font=font_body,
                        padding=4,
                        fieldbackground=bg_input,
                        foreground=text_primary,
                        background=bg_input,
                        arrowcolor=text_primary)
        style.map("TCombobox",
                  fieldbackground=[("readonly", bg_input), ("disabled", bg_sidebar)],
                  foreground=[("readonly", text_primary), ("disabled", text_disabled)],
                  background=[("readonly", bg_input)])

        self.root.option_add("*TCombobox*Listbox.background", bg_input)
        self.root.option_add("*TCombobox*Listbox.foreground", text_primary)
        self.root.option_add("*TCombobox*Listbox.selectBackground", accent)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")

        # Tk widgets
        self.root.option_add("*Text.background", bg_input)
        self.root.option_add("*Text.foreground", text_primary)
        self.root.option_add("*Text.insertBackground", text_primary)
        self.root.option_add("*Text.selectBackground", accent)
        self.root.option_add("*Text.selectForeground", "white")

        self.root.option_add("*Entry.background", bg_input)
        self.root.option_add("*Entry.foreground", text_primary)
        self.root.option_add("*Entry.insertBackground", text_primary)
        self.root.option_add("*Entry.selectBackground", accent)
        self.root.option_add("*Entry.selectForeground", "white")

        self.root.option_add("*Spinbox.background", bg_input)
        self.root.option_add("*Spinbox.foreground", text_primary)
        self.root.option_add("*Spinbox.insertBackground", text_primary)
        self.root.option_add("*Spinbox.selectBackground", accent)
        self.root.option_add("*Spinbox.selectForeground", "white")
        self.root.option_add("*Spinbox.buttonBackground", bg_sidebar)

        # Scrollbar
        self.root.option_add("*Scrollbar.background", get_color("scrollbar_fg"))
        self.root.option_add("*Scrollbar.troughColor", get_color("scrollbar_bg"))
        self.root.option_add("*Scrollbar.activeBackground", get_color("border_dark"))
        self.root.option_add("*Scrollbar.highlightBackground", bg_main)
        self.root.option_add("*Scrollbar.highlightColor", bg_main)

        # Checkbutton
        style.configure("TCheckbutton",
                        background=bg_main,
                        foreground=text_primary)
        style.map("TCheckbutton",
                  foreground=[("disabled", text_disabled)],
                  background=[("disabled", bg_main)])

        # Progressbar
        style.configure("TProgressbar",
                        background=accent,
                        troughcolor=get_color("scrollbar_bg"))

        # Separator
        style.configure("TSeparator", background=get_color("separator"))

        # ttk Scrollbar
        style.configure("TScrollbar",
                        background=get_color("scrollbar_fg"),
                        troughcolor=get_color("scrollbar_bg"))

        # LabelFrame
        style.configure("TLabelframe",
                        background=bg_main,
                        foreground=text_primary)
        style.configure("TLabelframe.Label",
                        background=bg_main,
                        foreground=text_primary,
                        font=font_subheading)

        # Base style
        style.configure(".", background=bg_main, foreground=text_primary)

    def _build_ui(self):
        """Build the main user interface with tabs."""
        # System footer at bottom
        from ui.system_footer import SystemFooter
        self.system_footer = SystemFooter(
            self.root,
            on_shutdown_callback=self._cleanup,
            vision_registry=self.vision_registry
        )

        # Main notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # Tab 1: Images (main functionality)
        self.images_frame = ttk.Frame(self.notebook, style="Main.TFrame")
        self.notebook.add(self.images_frame, text="  Images  ")

        # Configure grid for images tab
        self.images_frame.grid_rowconfigure(0, weight=1)
        self.images_frame.grid_columnconfigure(0, weight=0)
        self.images_frame.grid_columnconfigure(1, weight=1)

        # Tab 2: Settings
        self.settings_frame = ttk.Frame(self.notebook, style="Main.TFrame")
        self.notebook.add(self.settings_frame, text="  Settings  ")

        # Tab 3: Log
        self.log_frame = ttk.Frame(self.notebook, style="Main.TFrame")
        self.notebook.add(self.log_frame, text="  Log  ")

        # Tab 4: API
        self.api_frame = ttk.Frame(self.notebook, style="Main.TFrame")
        self.notebook.add(self.api_frame, text="  API  ")

        # Build each tab
        from ui.images_tab import ImagesTab
        from ui.settings_tab import SettingsTab
        from ui.log_tab import LogTab
        from ui.api_tab import APITab

        self.images_tab = ImagesTab(self.images_frame, self.vision_registry)
        self.settings_tab = SettingsTab(self.settings_frame)
        self.log_tab = LogTab(self.log_frame)
        self.api_tab = APITab(self.api_frame, self.api_server)

    def _on_close(self):
        """Handle window close button (X)."""
        logger.info("[App] Close button pressed")
        self.system_footer._on_shutdown()

    def _cleanup(self):
        """Extra cleanup before shutdown."""
        logger.info("[App] Running cleanup...")

        # Stop API server
        try:
            if self.api_server and self.api_server.is_running():
                logger.info("[App] Stopping API server...")
                self.api_server.stop()
        except Exception as e:
            logger.error(f"[App] API server cleanup error: {e}")

        # Shutdown image manager (cancels all downloads)
        try:
            self.image_manager.shutdown()  # Cancel all pending downloads
            self.image_manager.close()     # Close database
        except Exception as e:
            logger.error(f"[App] Cleanup error: {e}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    ImageBuddyApp().run()
