# core/theme.py
"""
Centralized theme configuration for ImageBuddy.
Supports light and dark modes with consistent color palettes.
"""

import os
import json
from pathlib import Path

# Config file location
CONFIG_DIR = Path(__file__).parent.parent / "config"
THEME_CONFIG_FILE = CONFIG_DIR / "theme.json"

# ============================================================================
# COLOR PALETTES
# ============================================================================

LIGHT = {
    # Backgrounds
    "bg_main": "#f5f5f5",
    "bg_card": "#ffffff",
    "bg_sidebar": "#eaeaea",
    "bg_input": "#ffffff",
    "bg_hover": "#e8f4fc",
    "bg_selected": "#d0e8f8",

    # Text
    "text_primary": "#212121",
    "text_secondary": "#555555",
    "text_hint": "#888888",
    "text_disabled": "#aaaaaa",

    # Accents
    "accent": "#0066cc",
    "accent_dark": "#0052a3",
    "accent_light": "#e3f2fd",

    # Status colors
    "success": "#4CAF50",
    "success_dark": "#388E3C",
    "success_light": "#66BB6A",
    "warning": "#FF9800",
    "warning_dark": "#F57C00",
    "danger": "#d32f2f",
    "danger_dark": "#b71c1c",
    "info": "#2196F3",

    # Borders & separators
    "border": "#cccccc",
    "border_light": "#e0e0e0",
    "border_dark": "#999999",
    "separator": "#dddddd",

    # Specific components
    "scrollbar_bg": "#e0e0e0",
    "scrollbar_fg": "#b0b0b0",
    "treeview_alt": "#fafafa",
    "tooltip_bg": "#333333",
    "tooltip_fg": "#ffffff",
}

DARK = {
    # Backgrounds
    "bg_main": "#1e1e1e",
    "bg_card": "#2d2d2d",
    "bg_sidebar": "#252525",
    "bg_input": "#3c3c3c",
    "bg_hover": "#383838",
    "bg_selected": "#404040",

    # Text
    "text_primary": "#e0e0e0",
    "text_secondary": "#b0b0b0",
    "text_hint": "#a0a0a0",
    "text_disabled": "#707070",

    # Accents
    "accent": "#3b9eff",
    "accent_dark": "#2d7fd4",
    "accent_light": "#1a3a52",

    # Status colors
    "success": "#81C784",
    "success_dark": "#66BB6A",
    "success_light": "#A5D6A7",
    "warning": "#FFCC80",
    "warning_dark": "#FFB74D",
    "danger": "#FF8A80",
    "danger_dark": "#FF6B6B",
    "info": "#42A5F5",

    # Borders & separators
    "border": "#444444",
    "border_light": "#3a3a3a",
    "border_dark": "#555555",
    "separator": "#404040",

    # Specific components
    "scrollbar_bg": "#2a2a2a",
    "scrollbar_fg": "#555555",
    "treeview_alt": "#262626",
    "tooltip_bg": "#e0e0e0",
    "tooltip_fg": "#1e1e1e",
}

# ============================================================================
# THEME STATE
# ============================================================================

_current_theme_name = "dark"  # Default to dark theme
_current_palette = DARK


def _load_saved_theme():
    """Load theme preference from config file."""
    global _current_theme_name, _current_palette

    try:
        if THEME_CONFIG_FILE.exists():
            with open(THEME_CONFIG_FILE, "r") as f:
                config = json.load(f)
                theme_name = config.get("theme", "dark")
                if theme_name == "light":
                    _current_theme_name = "light"
                    _current_palette = LIGHT
                else:
                    _current_theme_name = "dark"
                    _current_palette = DARK
    except Exception:
        pass


def _save_theme():
    """Save current theme preference to config file."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(THEME_CONFIG_FILE, "w") as f:
            json.dump({"theme": _current_theme_name}, f)
    except Exception:
        pass


# Load saved theme on module import
_load_saved_theme()


# ============================================================================
# PUBLIC API
# ============================================================================

def get_color(name: str) -> str:
    """Get a color from the current theme."""
    return _current_palette.get(name, "#ff00ff")


def get_palette() -> dict:
    """Get the entire current color palette."""
    return _current_palette.copy()


def get_theme_name() -> str:
    """Get current theme name ('light' or 'dark')."""
    return _current_theme_name


def is_dark() -> bool:
    """Check if dark theme is active."""
    return _current_theme_name == "dark"


def set_theme(theme_name: str):
    """Set the theme (requires app restart to take effect)."""
    global _current_theme_name, _current_palette

    if theme_name == "dark":
        _current_theme_name = "dark"
        _current_palette = DARK
    else:
        _current_theme_name = "light"
        _current_palette = LIGHT

    _save_theme()


def toggle_theme():
    """Toggle between light and dark themes."""
    if _current_theme_name == "light":
        set_theme("dark")
    else:
        set_theme("light")


# ============================================================================
# FONT DEFINITIONS
# ============================================================================

FONTS = {
    "heading": ("Segoe UI", 13, "bold"),
    "subheading": ("Segoe UI", 11, "bold"),
    "body": ("Segoe UI", 10),
    "small": ("Segoe UI", 9),
    "mono": ("Consolas", 10),
    "mono_small": ("Consolas", 9),
}


def get_font(name: str) -> tuple:
    """Get a font tuple."""
    return FONTS.get(name, FONTS["body"])


# ============================================================================
# WINDOW UTILITIES
# ============================================================================

def apply_dark_title_bar(window):
    """Apply dark title bar to a Toplevel window on Windows."""
    import sys
    if sys.platform != 'win32' or not is_dark():
        return

    def _apply():
        try:
            import ctypes
            window.update()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            if result != 0:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
        except:
            pass

    window.after(50, _apply)


def center_window_over_parent(window, parent=None):
    """Center a Toplevel window over its parent window."""
    window.update_idletasks()

    w = window.winfo_width()
    h = window.winfo_height()

    if parent is None:
        try:
            parent = window.master
        except:
            pass

    if parent and parent.winfo_exists():
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
    else:
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2

    window.geometry(f"+{x}+{y}")
