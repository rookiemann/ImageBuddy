# ui/ui_utils.py
# Reusable UI utilities for context menus, tooltips, and clipboard operations

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import io
import os
from core import theme


class ToolTip:
    """Simple tooltip that appears on hover."""

    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tooltip = None
        self.after_id = None

        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<Button>", self._hide)

    def _schedule(self, event=None):
        self._hide()
        self.after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if not self.text:
            return

        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tooltip = tk.Toplevel(self.widget)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        self.tooltip.configure(bg="#333333")

        label = tk.Label(
            self.tooltip,
            text=self.text,
            bg="#333333",
            fg="#ffffff",
            font=("Segoe UI", 9),
            padx=8,
            pady=4
        )
        label.pack()

    def _hide(self, event=None):
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def update_text(self, text):
        """Update tooltip text."""
        self.text = text


def add_tooltip(widget, text, delay=500):
    """Add a tooltip to a widget."""
    return ToolTip(widget, text, delay)


class TextContextMenu:
    """Right-click context menu for Text and Entry widgets."""

    def __init__(self, widget, readonly=False):
        self.widget = widget
        self.readonly = readonly
        self.menu = tk.Menu(widget, tearoff=0, bg="#2a2a2a", fg="#ffffff",
                            activebackground="#404040", activeforeground="#ffffff")

        if not readonly:
            self.menu.add_command(label="Cut", accelerator="Ctrl+X", command=self._cut)
        self.menu.add_command(label="Copy", accelerator="Ctrl+C", command=self._copy)
        if not readonly:
            self.menu.add_command(label="Paste", accelerator="Ctrl+V", command=self._paste)
            self.menu.add_separator()
            self.menu.add_command(label="Clear", command=self._clear)
        self.menu.add_separator()
        self.menu.add_command(label="Select All", accelerator="Ctrl+A", command=self._select_all)

        widget.bind("<Button-3>", self._show_menu)

    def _show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _cut(self):
        try:
            if isinstance(self.widget, tk.Text):
                if self.widget.tag_ranges(tk.SEL):
                    self.widget.event_generate("<<Cut>>")
            else:
                self.widget.event_generate("<<Cut>>")
        except:
            pass

    def _copy(self):
        try:
            if isinstance(self.widget, tk.Text):
                if self.widget.tag_ranges(tk.SEL):
                    self.widget.event_generate("<<Copy>>")
            else:
                self.widget.event_generate("<<Copy>>")
        except:
            pass

    def _paste(self):
        try:
            self.widget.event_generate("<<Paste>>")
        except:
            pass

    def _clear(self):
        try:
            if isinstance(self.widget, tk.Text):
                self.widget.delete("1.0", tk.END)
            else:
                self.widget.delete(0, tk.END)
        except:
            pass

    def _select_all(self):
        try:
            if isinstance(self.widget, tk.Text):
                self.widget.tag_add(tk.SEL, "1.0", tk.END)
            else:
                self.widget.select_range(0, tk.END)
        except:
            pass


def add_text_context_menu(widget, readonly=False):
    """Add right-click context menu to a Text or Entry widget."""
    return TextContextMenu(widget, readonly)


class ImageContextMenu:
    """Right-click context menu for gallery image cards."""

    def __init__(self, parent, on_copy_image=None, on_copy_caption=None, on_copy_url=None,
                 on_copy_tags=None, on_open_folder=None, on_delete=None, on_copy_all=None,
                 on_export=None):
        self.parent = parent
        self.menu = tk.Menu(parent, tearoff=0, bg="#2a2a2a", fg="#ffffff",
                            activebackground="#404040", activeforeground="#ffffff")

        self.current_image_data = None

        # Callbacks
        self.on_copy_image = on_copy_image
        self.on_copy_caption = on_copy_caption
        self.on_copy_url = on_copy_url
        self.on_copy_tags = on_copy_tags
        self.on_open_folder = on_open_folder
        self.on_delete = on_delete
        self.on_copy_all = on_copy_all
        self.on_export = on_export

        self._build_menu()

    def _build_menu(self):
        self.menu.add_command(label="Copy Image", command=self._copy_image)
        self.menu.add_command(label="Copy Caption", command=self._copy_caption)
        self.menu.add_command(label="Copy URL", command=self._copy_url)
        self.menu.add_command(label="Copy Tags", command=self._copy_tags)
        self.menu.add_separator()
        self.menu.add_command(label="Copy All Info", command=self._copy_all)
        self.menu.add_separator()
        self.menu.add_command(label="Open File Location", command=self._open_folder)
        self.menu.add_command(label="Export to Folder...", command=self._export)
        self.menu.add_separator()
        self.menu.add_command(label="Delete Image", command=self._delete, foreground="#ff6b6b")

    def show(self, event, image_data):
        """Show context menu for an image."""
        self.current_image_data = image_data
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _copy_image(self):
        if self.on_copy_image and self.current_image_data:
            self.on_copy_image(self.current_image_data)

    def _copy_caption(self):
        if self.current_image_data:
            caption = self.current_image_data.get("alt", "")
            if caption:
                self._copy_to_clipboard(caption)

    def _copy_url(self):
        if self.current_image_data:
            url = self.current_image_data.get("url", "")
            if url:
                self._copy_to_clipboard(url)

    def _copy_tags(self):
        if self.current_image_data:
            import json
            tags_str = self.current_image_data.get("tags", "[]")
            try:
                tags = json.loads(tags_str)
                if tags:
                    self._copy_to_clipboard(", ".join(tags))
            except:
                pass

    def _copy_all(self):
        if self.on_copy_all and self.current_image_data:
            self.on_copy_all(self.current_image_data)

    def _open_folder(self):
        if self.on_open_folder and self.current_image_data:
            self.on_open_folder(self.current_image_data)

    def _delete(self):
        if self.on_delete and self.current_image_data:
            self.on_delete(self.current_image_data)

    def _export(self):
        if self.on_export and self.current_image_data:
            self.on_export(self.current_image_data)

    def _copy_to_clipboard(self, text):
        self.parent.clipboard_clear()
        self.parent.clipboard_append(text)


def copy_image_to_clipboard(parent, image_path):
    """Copy an image file to the system clipboard (Windows)."""
    import sys
    if sys.platform != 'win32':
        return False

    try:
        import win32clipboard
        from PIL import Image
        import io

        # Open and convert image
        img = Image.open(image_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Convert to BMP format for clipboard
        output = io.BytesIO()
        img.save(output, 'BMP')
        data = output.getvalue()[14:]  # Remove BMP header
        output.close()

        # Copy to clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        win32clipboard.CloseClipboard()

        return True
    except ImportError:
        # win32clipboard not available, try alternative
        try:
            # Fallback: copy file path instead
            parent.clipboard_clear()
            parent.clipboard_append(image_path)
            return True
        except:
            return False
    except Exception as e:
        print(f"Failed to copy image: {e}")
        return False


def open_file_location(file_path):
    """Open the folder containing a file and select it."""
    import subprocess
    import sys

    if not os.path.exists(file_path):
        return False

    try:
        if sys.platform == 'win32':
            subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
        elif sys.platform == 'darwin':
            subprocess.run(['open', '-R', file_path])
        else:
            subprocess.run(['xdg-open', os.path.dirname(file_path)])
        return True
    except Exception as e:
        print(f"Failed to open file location: {e}")
        return False


def create_clear_button(parent, entry_widget, **kwargs):
    """Create a small 'X' button to clear an entry widget."""
    btn = tk.Button(
        parent,
        text="✕",
        font=("Segoe UI", 8),
        bg=theme.get_color("bg_sidebar"),
        fg=theme.get_color("text_secondary"),
        activebackground=theme.get_color("bg_hover"),
        activeforeground=theme.get_color("text_primary"),
        relief="flat",
        borderwidth=0,
        padx=4,
        pady=0,
        cursor="hand2",
        command=lambda: _clear_entry(entry_widget),
        **kwargs
    )
    add_tooltip(btn, "Clear")
    return btn


def _clear_entry(widget):
    """Clear an entry or text widget."""
    if isinstance(widget, tk.Text):
        widget.delete("1.0", tk.END)
    else:
        widget.delete(0, tk.END)
    widget.focus_set()
