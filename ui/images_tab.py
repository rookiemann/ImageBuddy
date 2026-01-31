# ui/images_tab.py
# Standalone Images Tab for ImageBuddy

import tkinter as tk
from tkinter import ttk
import json
import os
import uuid
import threading
import queue
import time
from pathlib import Path
from PIL import Image, ImageTk
from core import logger
from core import theme
from core.image_manager import ImageManager, THUMBS_DIR, ORIGINALS_DIR
from ui.ui_utils import (
    add_tooltip, add_text_context_menu, ImageContextMenu,
    copy_image_to_clipboard, open_file_location
)

# Settings config file
SETTINGS_FILE = Path(__file__).parent.parent / "config" / "settings.json"


def load_vision_settings() -> dict:
    """Load vision settings from config file."""
    from core import system_monitor

    defaults = {
        "vision_auto_load": True,
        "vision_auto_unload": False,
        "vision_gpu_strategy": "auto",
        "vision_gpu_enabled": {},
        "vision_gpu_instances": {},
        "vision_allow_cpu": None,  # Will be set based on GPU detection
        "vision_cpu_instances": 1,
        "vision_max_per_gpu": 4,
        "vision_max_total": 8,
        "vision_reserved_vram": 0.5,
    }
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                for key in defaults:
                    if key in saved:
                        defaults[key] = saved[key]
    except Exception as e:
        logger.error(f"[VISION] Failed to load settings: {e}")

    # If allow_cpu not explicitly set, default based on GPU availability
    if defaults["vision_allow_cpu"] is None:
        gpu_count = system_monitor.get_gpu_count()
        defaults["vision_allow_cpu"] = (gpu_count == 0)  # Only True if no GPUs

    return defaults


class ImagesTab:
    def __init__(self, parent_container, vision_registry):
        self.vision_registry = vision_registry
        self.manager = ImageManager()
        self.all_images = []
        self.visible_start = 0
        self.visible_count = 60
        self.card_pool = []
        self.photo_refs = {}
        self.vision_device_var = tk.StringVar()
        self.vision_count_var = tk.IntVar(value=1)
        self.vision_status_var = tk.StringVar(value="Florence-2: No instances loaded")

        self.vision_queue = queue.Queue()
        self.processing = False
        self.vision_worker_thread = None
        self.target_instance_count = 0
        self.loaded_instance_count = 0
        self.analysis_running = False
        self.stop_analysis_requested = False

        self.hover_popup = None
        self.hover_photo = None
        self.current_hover_card = None

        # Multi-select state
        self.selected_images = set()
        self.selection_mode = False

        # Image context menu (right-click)
        self.image_context_menu = None  # Initialized after UI is built

        self.filter_pixabay_var = tk.BooleanVar(value=False)
        self.filter_pexels_var = tk.BooleanVar(value=False)
        self.filter_unsplash_var = tk.BooleanVar(value=False)
        self.filter_url_var = tk.BooleanVar(value=True)
        self.filter_uploaded_var = tk.BooleanVar(value=True)

        self.apply_captions_var = tk.BooleanVar(value=True)
        self.apply_tags_var = tk.BooleanVar(value=True)

        self.override_short_caption_var = tk.BooleanVar(value=False)
        self.override_few_tags_var = tk.BooleanVar(value=False)

        # Scroll throttling
        self._scroll_after_id = None
        self._scroll_throttle_ms = 80

        # Download state (prevent double-starts)
        self._download_in_progress = False
        self._stop_download_requested = False

        # LRU thumbnail cache
        self._thumb_cache = {}
        self._thumb_cache_order = []
        self._thumb_cache_max = 250

        self.parent_container = parent_container

        # Left panel: search controls
        self.left_panel = ttk.Frame(self.parent_container, style="Sidebar.TFrame")
        self.left_panel.grid(row=0, column=0, sticky="ns", padx=(0, 12))

        self.left_canvas = tk.Canvas(self.left_panel, highlightthickness=0, background=theme.get_color("bg_sidebar"))
        self.left_scrollbar = ttk.Scrollbar(self.left_panel, orient="vertical", command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=self.left_scrollbar.set)

        self.left_frame = ttk.Frame(self.left_canvas, style="Sidebar.TFrame", padding="20")
        self.left_canvas.create_window((0, 0), window=self.left_frame, anchor="nw")

        self.left_canvas.pack(side="left", fill="both", expand=True)
        self.left_scrollbar.pack(side="right", fill="y")

        self.left_frame.bind("<Configure>", lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))
        self.left_canvas.bind("<Configure>", lambda e: self.left_canvas.itemconfig(self.left_canvas.find_withtag("all")[0], width=e.width - 10))

        # Mouse wheel for left panel
        def on_left_mousewheel(event):
            self.left_canvas.yview_scroll(-int(event.delta / 120), "units")

        def bind_left_wheel(event=None):
            self.left_canvas.bind_all("<MouseWheel>", on_left_mousewheel)

        def unbind_left_wheel(event=None):
            self.left_canvas.unbind_all("<MouseWheel>")

        self.left_canvas.bind("<Enter>", lambda e: bind_left_wheel())
        self.left_canvas.bind("<Leave>", lambda e: unbind_left_wheel())
        bind_left_wheel()

        # Right panel: gallery
        self.right_panel = ttk.Frame(self.parent_container, style="Main.TFrame")
        self.right_panel.grid(row=0, column=1, sticky="nsew")

        self.right_panel.grid_rowconfigure(0, weight=0)
        self.right_panel.grid_rowconfigure(1, weight=0)
        self.right_panel.grid_rowconfigure(2, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)

        # Build UI
        self._build_left_search()
        self._build_right_gallery()

        # Initialize image context menu (right-click menu for gallery)
        self._init_image_context_menu()

        # Add context menus and tooltips
        self._add_ui_enhancements()

        # Load images in background
        self.parent_container.after(50, self._load_all_images_async)

        # Analysis filters in a clean labeled frame
        filters_frame = ttk.LabelFrame(self.left_frame, text="Analysis Options", padding=(15, 10))
        filters_frame.grid(row=19, column=0, sticky="ew", pady=(20, 10))

        # Use grid layout with fixed label width for alignment
        filters_frame.grid_columnconfigure(1, weight=1)

        # Sources row
        ttk.Label(filters_frame, text="Sources:", width=10, anchor="w").grid(
            row=0, column=0, sticky="w", pady=(0, 8))

        src_frame = ttk.Frame(filters_frame)
        src_frame.grid(row=0, column=1, sticky="w", pady=(0, 8))
        ttk.Checkbutton(src_frame, text="Pixabay", variable=self.filter_pixabay_var).pack(side="left", padx=(0, 15))
        ttk.Checkbutton(src_frame, text="Pexels", variable=self.filter_pexels_var).pack(side="left", padx=(0, 15))
        ttk.Checkbutton(src_frame, text="Unsplash", variable=self.filter_unsplash_var).pack(side="left", padx=(0, 15))
        ttk.Checkbutton(src_frame, text="URLs", variable=self.filter_url_var).pack(side="left", padx=(0, 15))
        ttk.Checkbutton(src_frame, text="Local", variable=self.filter_uploaded_var).pack(side="left")

        ttk.Separator(filters_frame, orient="horizontal").grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)

        # Apply row
        ttk.Label(filters_frame, text="Apply:", width=10, anchor="w").grid(
            row=2, column=0, sticky="w", pady=(0, 8))

        apply_frame = ttk.Frame(filters_frame)
        apply_frame.grid(row=2, column=1, sticky="w", pady=(0, 8))
        ttk.Checkbutton(apply_frame, text="Captions", variable=self.apply_captions_var).pack(side="left", padx=(0, 15))
        ttk.Checkbutton(apply_frame, text="Tags", variable=self.apply_tags_var).pack(side="left")

        # Re-run row
        ttk.Label(filters_frame, text="Re-run:", width=10, anchor="w").grid(
            row=3, column=0, sticky="w")

        rerun_frame = ttk.Frame(filters_frame)
        rerun_frame.grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(rerun_frame, text="Short captions", variable=self.override_short_caption_var).pack(side="left", padx=(0, 15))
        ttk.Checkbutton(rerun_frame, text="Few tags", variable=self.override_few_tags_var).pack(side="left")

        # Vision status
        ttk.Label(self.left_frame, textvariable=self.vision_status_var, style="Hint.TLabel") \
            .grid(row=20, column=0, sticky="w", pady=(10, 20))

        def enforce_at_least_one(*args):
            if not self.apply_captions_var.get() and not self.apply_tags_var.get():
                self.apply_captions_var.set(True)

        self.apply_captions_var.trace_add("write", enforce_at_least_one)
        self.apply_tags_var.trace_add("write", enforce_at_least_one)

    def _init_image_context_menu(self):
        """Initialize the right-click context menu for gallery images."""
        self.image_context_menu = ImageContextMenu(
            self.right_panel,
            on_copy_image=self._ctx_copy_image,
            on_copy_caption=None,  # Handled internally by ImageContextMenu
            on_copy_url=None,  # Handled internally
            on_copy_tags=None,  # Handled internally
            on_copy_all=self._ctx_copy_all_info,
            on_open_folder=self._ctx_open_folder,
            on_delete=self._ctx_delete_image,
            on_export=self._ctx_export_image
        )

    def _ctx_copy_image(self, img_data):
        """Copy image to clipboard."""
        path = None
        if img_data.get("path"):
            path = os.path.join("images", "originals", img_data["filename"])
        elif img_data.get("thumb_path"):
            path = os.path.join("images", "thumbs", os.path.basename(img_data["thumb_path"]))

        if path and os.path.exists(path):
            full_path = os.path.abspath(path)
            if copy_image_to_clipboard(self.right_panel, full_path):
                self.gallery_status.set("Image copied to clipboard")
            else:
                # Fallback: copy file path
                self.right_panel.clipboard_clear()
                self.right_panel.clipboard_append(full_path)
                self.gallery_status.set("Image path copied to clipboard")
        else:
            self.gallery_status.set("Image file not found")

    def _ctx_copy_all_info(self, img_data):
        """Copy all image metadata to clipboard."""
        lines = []
        lines.append(f"ID: {img_data.get('id', '')}")
        if img_data.get('alt'):
            lines.append(f"Caption: {img_data['alt']}")
        if img_data.get('url'):
            lines.append(f"URL: {img_data['url']}")
        lines.append(f"Source: {img_data.get('source', '')}")
        lines.append(f"Query: {img_data.get('query', '')}")
        lines.append(f"Size: {img_data.get('width', '?')}x{img_data.get('height', '?')}")

        if img_data.get('tags'):
            try:
                tags = json.loads(img_data['tags'])
                lines.append(f"Tags: {', '.join(tags)}")
            except:
                pass

        if img_data.get('path'):
            lines.append(f"File: {img_data['path']}")

        text = "\n".join(lines)
        self.right_panel.clipboard_clear()
        self.right_panel.clipboard_append(text)
        self.gallery_status.set("All info copied to clipboard")

    def _ctx_open_folder(self, img_data):
        """Open the folder containing the image."""
        path = None
        if img_data.get("path"):
            path = os.path.join("images", "originals", img_data["filename"])
        elif img_data.get("thumb_path"):
            path = os.path.join("images", "thumbs", os.path.basename(img_data["thumb_path"]))

        if path and os.path.exists(path):
            full_path = os.path.abspath(path)
            if open_file_location(full_path):
                self.gallery_status.set("Opened folder")
            else:
                self.gallery_status.set("Could not open folder")
        else:
            self.gallery_status.set("File not found")

    def _ctx_delete_image(self, img_data):
        """Delete a single image from context menu."""
        image_id = img_data.get('id')
        if image_id:
            deleted, failed = self.manager.delete_images([image_id])
            if deleted > 0:
                self.gallery_status.set("Image deleted")
                self._load_all_images_async()
            else:
                self.gallery_status.set("Failed to delete image")

    def _ctx_export_image(self, img_data):
        """Export a single image from context menu."""
        from tkinter import filedialog
        import shutil

        # Get original file path
        filename = img_data.get("filename", "")
        if not filename:
            self.gallery_status.set("No file to export")
            return

        original_path = ORIGINALS_DIR / filename
        if not original_path.exists():
            self.gallery_status.set("Original file not found")
            return

        # Ask user for export directory
        export_dir = filedialog.askdirectory(
            title="Export Image to Directory",
            mustexist=False
        )

        if not export_dir:
            return  # User cancelled

        export_path = Path(export_dir)

        # Create directory if it doesn't exist
        try:
            export_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.gallery_status.set(f"Error: {e}")
            return

        # Copy image file
        try:
            dest_path = export_path / filename
            shutil.copy2(original_path, dest_path)

            # Create info text file for this image
            info_file = export_path / f"{Path(filename).stem}_info.txt"
            with open(info_file, "w", encoding="utf-8") as f:
                f.write(f"Filename: {filename}\n")
                f.write(f"Original Path: {original_path}\n")
                if img_data.get("url"):
                    f.write(f"Source URL: {img_data['url']}\n")
                if img_data.get("alt"):
                    f.write(f"Caption: {img_data['alt']}\n")
                if img_data.get("source"):
                    f.write(f"Source: {img_data['source']}\n")
                if img_data.get("tags"):
                    try:
                        tags = json.loads(img_data["tags"])
                        f.write(f"Tags: {', '.join(tags)}\n")
                    except:
                        pass

            self.gallery_status.set(f"Exported to {export_path.name}")
            self._open_export_folder(export_path)

        except Exception as e:
            logger.error(f"[EXPORT] Failed to export: {e}")
            self.gallery_status.set(f"Export failed: {e}")

    def _add_ui_enhancements(self):
        """Add context menus and tooltips to UI elements."""
        # Add context menu to URL text area
        add_text_context_menu(self.url_text)

        # Add context menu to search entry
        add_text_context_menu(self.query_entry)

        # Add tooltips to buttons
        add_tooltip(self.auto_load_btn, "Auto-detect GPU and load optimal Florence-2 instances")
        add_tooltip(self.analyze_btn, "Analyze images with Florence-2 to generate captions and tags")
        add_tooltip(self.unload_btn, "Unload all Florence-2 instances to free GPU memory")
        add_tooltip(self.add_images_btn, "Download images from the URLs entered above")

        # Filter button tooltip
        add_tooltip(self.clear_filters_btn, "Reset search and filters")

        # Selection action tooltips
        add_tooltip(self.clear_selection_btn, "Deselect all selected images")
        add_tooltip(self.delete_selected_btn, "Permanently delete selected images")
        add_tooltip(self.export_selected_btn, "Export selected images to a folder with source info")

    def _load_all_images(self):
        self.all_images = self.manager.get_all_images()
        self._initial_display()

    def _load_all_images_async(self):
        self.gallery_status.set("Loading...")

        def load():
            images = self.manager.get_all_images()
            self.parent_container.after(0, lambda: self._finish_load(images))

        threading.Thread(target=load, daemon=True).start()

    def _finish_load(self, images):
        self.all_images = images
        self._initial_display()

    def _initial_display(self):
        self.gallery_status.set(f"{len(self.all_images)} saved images")
        self._update_visible_cards_chunked()

    def _update_visible_cards_chunked(self):
        """Update visible cards progressively to keep UI responsive."""
        # Cancel any pending chunked update
        if hasattr(self, '_chunk_pending') and self._chunk_pending:
            try:
                self.parent_container.after_cancel(self._chunk_pending)
            except:
                pass
            self._chunk_pending = None

        end = min(self.visible_start + self.visible_count, len(self.all_images))
        visible_images = self.all_images[self.visible_start:end]

        # Hide cards in chunks, then load new ones
        self._hide_cards_chunk(0, visible_images, chunk_size=30)

    def _hide_cards_chunk(self, start_idx, visible_images, chunk_size=30):
        end_idx = min(start_idx + chunk_size, len(self.card_pool))
        for i in range(start_idx, end_idx):
            self.card_pool[i].grid_remove()

        if end_idx < len(self.card_pool):
            self._chunk_pending = self.parent_container.after_idle(
                lambda: self._hide_cards_chunk(end_idx, visible_images, chunk_size)
            )
        else:
            if visible_images:
                self._chunk_pending = self.parent_container.after_idle(
                    lambda: self._load_cards_chunk(visible_images, 0, chunk_size=8)
                )

    def _load_cards_chunk(self, visible_images, start_idx, chunk_size=8):
        """Load a chunk of cards into the grid."""
        end_idx = min(start_idx + chunk_size, len(visible_images))
        for idx in range(start_idx, end_idx):
            img = visible_images[idx]
            self._setup_single_card(idx, img)

        if end_idx < len(visible_images):
            self._chunk_pending = self.parent_container.after_idle(
                lambda: self._load_cards_chunk(visible_images, end_idx, chunk_size)
            )
        else:
            self._chunk_pending = None
            # Force geometry update before setting scroll region
            self.gallery_frame.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _setup_single_card(self, idx, img):
        """Set up a single card widget."""
        # Ensure we have enough cards in the pool
        while len(self.card_pool) <= idx:
            self._create_card_widget()

        card = self.card_pool[idx]
        img_id = img["id"]

        # Grid position (4 columns)
        row = idx // 4
        col = idx % 4
        card.grid(row=row, column=col, padx=6, pady=10, sticky="nsew")

        # Get thumbnail path
        thumb_path = None
        if img.get("thumb_path"):
            thumb_path = os.path.join("images", "thumbs", os.path.basename(img["thumb_path"]))
        elif img.get("path"):
            thumb_path = os.path.join("images", "originals", img["filename"])

        # Use cached thumbnail if available
        photo = self._get_cached_thumbnail(thumb_path, size=150)
        card.img_label.configure(image=photo)
        card.source_label.configure(text=img["source"])

        # Tags
        if img.get("tags"):
            try:
                tags_list = json.loads(img["tags"])
                display_tags = tags_list[:4]
                tags_text = ", ".join(display_tags)
                if len(tags_list) > 4:
                    tags_text += "..."
                card.tags_label.configure(text=tags_text)
            except:
                card.tags_label.configure(text="")
        else:
            card.tags_label.configure(text="")

        # Update selection visual
        is_selected = img_id in self.selected_images
        self._update_card_selection_visual(card, is_selected)

        # Click binding for selection toggle
        def on_click(e, image_id=img_id, c=card):
            self._toggle_image_selection(image_id, c)

        card.bind("<Button-1>", on_click)
        card.img_label.bind("<Button-1>", on_click)

        # Hover bindings
        card.bind("<Enter>", lambda e, i=img: self._show_hover(e, i))
        card.bind("<Leave>", lambda e: self._hide_hover())
        card.img_label.bind("<Enter>", lambda e, i=img: self._show_hover(e, i))
        card.img_label.bind("<Leave>", lambda e: self._hide_hover())

        # Right-click context menu
        def on_right_click(e, image_data=img):
            self._hide_hover()  # Hide hover popup when showing context menu
            if self.image_context_menu:
                self.image_context_menu.show(e, image_data)

        card.bind("<Button-3>", on_right_click)
        card.img_label.bind("<Button-3>", on_right_click)

    def _build_left_search(self):
        ttk.Label(self.left_frame, text="Image Search", style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 20))
        ttk.Label(self.left_frame, text="Search free stock photos - results automatically saved.", style="Hint.TLabel") \
            .grid(row=1, column=0, sticky="w", pady=(0, 30))

        entry_frame = ttk.Frame(self.left_frame)
        entry_frame.grid(row=2, column=0, sticky="ew", pady=(0, 20))
        entry_frame.grid_columnconfigure(0, weight=1)

        self.query_var = tk.StringVar()
        self.query_entry = ttk.Entry(entry_frame, textvariable=self.query_var, font=("Helvetica", 11))
        self.query_entry.grid(row=0, column=0, sticky="ew")
        self.query_entry.insert(0, "Enter search term and press Enter")
        self.query_entry.configure(foreground=theme.get_color("text_hint"))

        def on_focus_in(e):
            if self.query_entry.get() == "Enter search term and press Enter":
                self.query_entry.delete(0, tk.END)
                self.query_entry.configure(foreground=theme.get_color("text_primary"))

        def on_focus_out(e):
            if not self.query_entry.get().strip():
                self.query_entry.insert(0, "Enter search term and press Enter")
                self.query_entry.configure(foreground=theme.get_color("text_hint"))

        self.query_entry.bind("<FocusIn>", on_focus_in)
        self.query_entry.bind("<FocusOut>", on_focus_out)
        self.query_entry.bind("<Return>", lambda e: self._start_search())
        self.query_entry.bind("<KP_Enter>", lambda e: self._start_search())

        self.preview_mode_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.left_frame,
            text="Preview mode (thumbnails only)",
            variable=self.preview_mode_var
        ).grid(row=3, column=0, sticky="w", pady=(0, 20))

        controls = ttk.Frame(self.left_frame)
        controls.grid(row=4, column=0, sticky="w", pady=(0, 30))

        self.sources = {
            "pixabay": tk.BooleanVar(value=True),
            "pexels": tk.BooleanVar(value=True),
            "unsplash": tk.BooleanVar(value=True)
        }
        self.limits = {
            "pixabay": tk.IntVar(value=1),
            "pexels": tk.IntVar(value=1),
            "unsplash": tk.IntVar(value=1)
        }

        r = 0
        for src in self.sources:
            ttk.Checkbutton(controls, text=src.capitalize(), variable=self.sources[src]) \
                .grid(row=r, column=0, sticky="w", pady=4)
            ttk.Label(controls, text="Pages:").grid(row=r, column=1, sticky="e", padx=(30, 5))
            ttk.Spinbox(controls, from_=1, to=10, width=5, textvariable=self.limits[src]) \
                .grid(row=r, column=2, sticky="w", padx=(0, 20))
            r += 1

        ttk.Label(
            controls,
            text="Each page: Pixabay=200, Pexels=80, Unsplash=30 images",
            style="Hint.TLabel",
            foreground=theme.get_color("text_secondary")
        ).grid(row=r, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.search_status = tk.StringVar(value="Ready")
        ttk.Label(self.left_frame, textvariable=self.search_status, style="Hint.TLabel").grid(row=5, column=0, sticky="w", pady=(20, 0))

        ttk.Separator(self.left_frame, orient="horizontal").grid(row=6, column=0, sticky="ew", pady=(20, 20))

        ttk.Label(self.left_frame, text="Add Images from URLs", style="Heading.TLabel").grid(row=7, column=0, sticky="w", pady=(0, 10))
        ttk.Label(
            self.left_frame,
            text="Paste direct image URLs here, one per line.",
            style="Hint.TLabel",
            foreground=theme.get_color("text_secondary"),
            wraplength=400
        ).grid(row=8, column=0, sticky="w", pady=(0, 10))

        url_frame = ttk.Frame(self.left_frame)
        url_frame.grid(row=9, column=0, sticky="nsew", pady=(0, 15))
        url_frame.grid_rowconfigure(0, weight=1)
        url_frame.grid_columnconfigure(0, weight=1)

        self.url_text = tk.Text(
            url_frame,
            height=12,
            font=("Helvetica", 10),
            background=theme.get_color("bg_input"),
            foreground=theme.get_color("text_primary"),
            insertbackground=theme.get_color("text_primary"),
            selectbackground=theme.get_color("accent"),
            selectforeground="white"
        )
        self.url_text.grid(row=0, column=0, sticky="nsew")
        v_scroll = ttk.Scrollbar(url_frame, orient="vertical", command=self.url_text.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        self.url_text.configure(yscrollcommand=v_scroll.set)

        meta_frame = ttk.LabelFrame(self.left_frame, text="Metadata for all images")
        meta_frame.grid(row=10, column=0, sticky="ew", pady=(0, 15))
        meta_frame.grid_columnconfigure(1, weight=1)

        self.manual_query_var = tk.StringVar()
        self.manual_source_var = tk.StringVar(value="Manual")
        self.manual_tags_var = tk.StringVar()
        self.manual_alt_var = tk.StringVar()

        fields = [
            ("Search term / Category:", self.manual_query_var),
            ("Source name:", self.manual_source_var),
            ("Tags (comma separated):", self.manual_tags_var),
            ("Alt text / Description:", self.manual_alt_var)
        ]

        for i, (label, var) in enumerate(fields):
            ttk.Label(meta_frame, text=label).grid(row=i, column=0, sticky="w", padx=10, pady=6)
            ttk.Entry(meta_frame, textvariable=var).grid(row=i, column=1, sticky="ew", padx=(0, 10), pady=6)

        options_frame = ttk.Frame(self.left_frame)
        options_frame.grid(row=11, column=0, sticky="ew", pady=(0, 20))
        options_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(
            options_frame,
            text="Metadata below applies to both URL and local images",
            foreground=theme.get_color("text_secondary"), font=("Helvetica", 9), wraplength=400
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.manual_full_download_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame,
            text="Download full resolution images",
            variable=self.manual_full_download_var
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        ttk.Label(
            options_frame,
            text="(Unchecked = thumbnails only)",
            foreground=theme.get_color("text_secondary"), font=("Helvetica", 9)
        ).grid(row=2, column=0, sticky="w", pady=(0, 15))

        button_frame = ttk.Frame(options_frame)
        button_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)

        self.add_images_btn = ttk.Button(
            button_frame,
            text="Add Images (URLs)",
            style="Small.Primary.TButton",
            command=self._toggle_manual_download
        )
        self.add_images_btn.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        ttk.Button(
            button_frame,
            text="Add Local Images...",
            style="Small.Primary.TButton",
            command=self._add_local_images
        ).grid(row=0, column=1, padx=(8, 0), sticky="ew")

        # Florence-2 Vision Engine Section
        ttk.Separator(self.left_frame, orient="horizontal").grid(row=12, column=0, sticky="ew", pady=(40, 20))

        ttk.Label(self.left_frame, text="Florence-2 Vision Engine", style="Heading.TLabel") \
            .grid(row=13, column=0, sticky="w", pady=(0, 10))

        ttk.Label(self.left_frame,
                  text="Auto-detect your GPU and load optimal instances, or configure manually.",
                  style="Hint.TLabel") \
            .grid(row=14, column=0, sticky="w", pady=(0, 20))

        # Auto Load button (simple mode)
        auto_frame = ttk.Frame(self.left_frame)
        auto_frame.grid(row=15, column=0, sticky="ew", pady=(0, 15))

        self.auto_load_btn = ttk.Button(
            auto_frame,
            text="Auto Load (Recommended)",
            style="Primary.TButton",
            command=self._auto_load_vision
        )
        self.auto_load_btn.pack(side="left", fill="x", expand=True)

        # Expandable advanced options
        self.show_advanced_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.left_frame,
            text="Show advanced options",
            variable=self.show_advanced_var,
            command=self._toggle_advanced_vision
        ).grid(row=16, column=0, sticky="w", pady=(0, 10))

        # Advanced options frame (hidden by default)
        self.advanced_frame = ttk.LabelFrame(self.left_frame, text="Manual Configuration", padding=(10, 5))
        self.advanced_frame.grid(row=17, column=0, sticky="ew", pady=(0, 15))
        self.advanced_frame.grid_remove()  # Hidden initially
        self.advanced_frame.grid_columnconfigure(1, weight=1)

        from gpu_utils import get_available_gpus, get_default_selection
        devices = get_available_gpus()

        # Device row
        ttk.Label(self.advanced_frame, text="Device:", width=10, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 8), pady=4)
        self.vision_device_combo = ttk.Combobox(
            self.advanced_frame,
            textvariable=self.vision_device_var,
            values=devices,
            state="readonly"
        )
        self.vision_device_combo.grid(row=0, column=1, sticky="ew", pady=4)

        default_device = get_default_selection()
        self.vision_device_var.set(default_device)

        # Instances row
        ttk.Label(self.advanced_frame, text="Instances:", width=10, anchor="e").grid(
            row=1, column=0, sticky="e", padx=(0, 8), pady=4)
        ttk.Spinbox(
            self.advanced_frame,
            from_=1,
            to=10,
            textvariable=self.vision_count_var,
            width=8
        ).grid(row=1, column=1, sticky="w", pady=4)

        # Load button
        self.load_vision_btn = ttk.Button(
            self.advanced_frame,
            text="Load Instances",
            style="Small.Primary.TButton",
            command=self._load_vision_instances
        )
        self.load_vision_btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))

        # Main button frame (always visible)
        btn_frame = ttk.Frame(self.left_frame)
        btn_frame.grid(row=18, column=0, sticky="ew", pady=(0, 20))
        btn_frame.grid_columnconfigure(0, weight=1, uniform="visionbtn")
        btn_frame.grid_columnconfigure(1, weight=1, uniform="visionbtn")

        # Use tk.Button for danger buttons (ttk doesn't apply foreground color properly)
        self.unload_btn = tk.Button(
            btn_frame,
            text="Unload All",
            command=self._unload_all_vision,
            bg="#d32f2f",
            fg="#ffffff",
            activebackground="#b71c1c",
            activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief="raised",
            borderwidth=1,
            padx=10,
            pady=4,
            state="disabled",
            disabledforeground="#999999"
        )
        self.unload_btn.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.analyze_btn = ttk.Button(
            btn_frame,
            text="Analyze Images",
            style="Small.Primary.TButton",
            command=self._toggle_analysis,
            width=16
        )
        self.analyze_btn.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        # Stop button (tk.Button for proper danger styling)
        self.stop_btn = tk.Button(
            btn_frame,
            text="Stop Analysis",
            command=self._request_stop_analysis,
            bg=theme.get_color("danger"),
            fg="white",
            activebackground=theme.get_color("danger_dark"),
            activeforeground="white",
            font=theme.get_font("body"),
            relief="flat",
            padx=10,
            pady=4,
            state="disabled",
            disabledforeground="#888888"
        )
        self.stop_btn.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky="ew")
        self.stop_btn.grid_remove()  # Hidden until analysis starts

        self.left_frame.grid_rowconfigure(9, weight=1)
        self.left_frame.grid_columnconfigure(0, weight=1)

    def _build_right_gallery(self):
        # Main search container
        search_container = ttk.Frame(self.right_panel)
        search_container.grid(row=0, column=0, sticky="ew", pady=(8, 6))
        search_container.grid_columnconfigure(0, weight=1)

        # Simple search row
        simple_search_frame = ttk.Frame(search_container)
        simple_search_frame.grid(row=0, column=0, sticky="ew")
        simple_search_frame.grid_columnconfigure(0, weight=1)

        self.filter_var = tk.StringVar()
        entry = ttk.Entry(simple_search_frame, textvariable=self.filter_var, font=("Helvetica", 11))
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        entry.insert(0, "Search saved images (text, tags, caption)...")
        entry.bind("<FocusIn>", lambda e: entry.delete(0, "end") if entry.get().startswith("Search saved") else None)
        entry.bind("<Return>", lambda e: self._apply_filter())
        entry.bind("<KP_Enter>", lambda e: self._apply_filter())

        # Advanced search toggle button
        self.advanced_search_visible = False
        self.advanced_toggle_btn = ttk.Button(
            simple_search_frame,
            text="Advanced",
            style="Small.TButton",
            command=self._toggle_advanced_search,
            width=10
        )
        self.advanced_toggle_btn.grid(row=0, column=1, padx=(0, 10))

        # Clear filters button
        self.clear_filters_btn = ttk.Button(
            simple_search_frame,
            text="Clear",
            style="Small.TButton",
            command=self._clear_all_filters,
            width=6
        )
        self.clear_filters_btn.grid(row=0, column=2, padx=(0, 10))

        # Advanced search panel (collapsible)
        self.advanced_search_frame = ttk.Frame(search_container, style="Card.TFrame")
        self.advanced_search_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.advanced_search_frame.grid_remove()  # Hidden initially
        self._build_advanced_search_panel()

        # Selection frame (moved outside filter_frame)
        self.selection_frame = ttk.Frame(simple_search_frame)
        self.selection_frame.grid(row=0, column=3, sticky="e")
        self.selection_frame.grid_remove()  # Hidden initially until images are selected

        self.selection_label = ttk.Label(
            self.selection_frame,
            text="",
            font=("Segoe UI", 9),
            foreground=theme.get_color("accent")
        )
        self.selection_label.pack(side="left", padx=(0, 10))

        self.clear_selection_btn = ttk.Button(
            self.selection_frame,
            text="Deselect",
            style="Small.TButton",
            command=self._clear_selection,
            width=8
        )
        self.clear_selection_btn.pack(side="left", padx=(0, 6))
        self.clear_selection_btn.pack_forget()

        self.export_selected_btn = ttk.Button(
            self.selection_frame,
            text="Export Selected",
            style="Small.TButton",
            command=self._export_selected_images,
            width=14
        )
        self.export_selected_btn.pack(side="left", padx=(0, 6))
        self.export_selected_btn.pack_forget()

        self.delete_selected_btn = ttk.Button(
            self.selection_frame,
            text="Delete Selected",
            style="Small.Danger.TButton",
            command=self._delete_selected_images,
            width=14
        )
        self.delete_selected_btn.pack(side="left")
        self.delete_selected_btn.pack_forget()

        self.gallery_status = tk.StringVar(value="Loading saved images...")
        ttk.Label(self.right_panel, textvariable=self.gallery_status, style="Hint.TLabel") \
            .grid(row=1, column=0, sticky="w", pady=(0, 10))

        self.canvas = tk.Canvas(self.right_panel, background=theme.get_color("bg_main"), highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.right_panel, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.gallery_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")

        for i in range(4):
            self.gallery_frame.grid_columnconfigure(i, weight=1, uniform="col")

        self.canvas.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")

        def on_configure(event):
            self.canvas.itemconfig(self.canvas.find_withtag("gallery"), width=event.width)
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        self.canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw", tags="gallery")
        self.canvas.bind("<Configure>", on_configure)

        def on_mousewheel(event):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

        def bind_wheel(event=None):
            self.canvas.bind_all("<MouseWheel>", on_mousewheel)

        def unbind_wheel(event=None):
            self.canvas.unbind_all("<MouseWheel>")

        self.canvas.bind("<Enter>", lambda e: bind_wheel())
        self.canvas.bind("<Leave>", lambda e: unbind_wheel())
        bind_wheel()

        # Scroll tracking for virtualization (throttled)
        def on_scroll(*_):
            # Cancel pending update if any
            if self._scroll_after_id is not None:
                self.canvas.after_cancel(self._scroll_after_id)

            # Schedule update after throttle delay
            def do_update():
                self._scroll_after_id = None
                visible = self.canvas.yview()
                total = len(self.all_images)
                if total == 0:
                    return
                start = int(visible[0] * total)
                self.visible_start = max(0, start - 20)
                self._update_visible_cards()

            self._scroll_after_id = self.canvas.after(self._scroll_throttle_ms, do_update)

        self.canvas.bind("<Configure>", lambda e: on_scroll())
        scrollbar.config(command=lambda *args: (self.canvas.yview(*args), on_scroll()))
        self.canvas.bind_all("<MouseWheel>", lambda e: on_scroll())

    def _toggle_advanced_search(self):
        """Toggle visibility of advanced search panel."""
        self.advanced_search_visible = not self.advanced_search_visible
        if self.advanced_search_visible:
            self.advanced_search_frame.grid()
            self.advanced_toggle_btn.config(text="Hide")
        else:
            self.advanced_search_frame.grid_remove()
            self.advanced_toggle_btn.config(text="Advanced")

    def _build_advanced_search_panel(self):
        """Build the advanced search options panel with proper grid alignment."""
        self.advanced_search_frame.grid_columnconfigure(0, weight=1)

        # Use a single grid layout for clean alignment
        grid_frame = ttk.Frame(self.advanced_search_frame)
        grid_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        grid_frame.grid_columnconfigure(1, weight=1)
        grid_frame.grid_columnconfigure(3, weight=1)
        grid_frame.grid_columnconfigure(5, weight=1)

        # Row 0: Include / Exclude / Source
        ttk.Label(grid_frame, text="Include:", width=8, anchor="e").grid(row=0, column=0, sticky="e", padx=(0, 5), pady=4)
        self.search_include_var = tk.StringVar()
        ttk.Entry(grid_frame, textvariable=self.search_include_var).grid(row=0, column=1, sticky="ew", padx=(0, 15), pady=4)

        ttk.Label(grid_frame, text="Exclude:", width=8, anchor="e").grid(row=0, column=2, sticky="e", padx=(0, 5), pady=4)
        self.search_exclude_var = tk.StringVar()
        ttk.Entry(grid_frame, textvariable=self.search_exclude_var).grid(row=0, column=3, sticky="ew", padx=(0, 15), pady=4)

        ttk.Label(grid_frame, text="Source:", width=8, anchor="e").grid(row=0, column=4, sticky="e", padx=(0, 5), pady=4)
        self.search_source_var = tk.StringVar(value="All")
        ttk.Combobox(grid_frame, textvariable=self.search_source_var,
                     values=["All", "Pixabay", "Pexels", "Unsplash", "Manual", "Local", "URL"],
                     state="readonly", width=12).grid(row=0, column=5, sticky="w", pady=4)

        # Row 1: Width range / Height range / Aspect
        ttk.Label(grid_frame, text="Width:", width=8, anchor="e").grid(row=1, column=0, sticky="e", padx=(0, 5), pady=4)
        width_frame = ttk.Frame(grid_frame)
        width_frame.grid(row=1, column=1, sticky="ew", padx=(0, 15), pady=4)
        self.search_min_width_var = tk.StringVar()
        self.search_max_width_var = tk.StringVar()
        ttk.Entry(width_frame, textvariable=self.search_min_width_var, width=7).pack(side="left")
        ttk.Label(width_frame, text=" - ").pack(side="left")
        ttk.Entry(width_frame, textvariable=self.search_max_width_var, width=7).pack(side="left")

        ttk.Label(grid_frame, text="Height:", width=8, anchor="e").grid(row=1, column=2, sticky="e", padx=(0, 5), pady=4)
        height_frame = ttk.Frame(grid_frame)
        height_frame.grid(row=1, column=3, sticky="ew", padx=(0, 15), pady=4)
        self.search_min_height_var = tk.StringVar()
        self.search_max_height_var = tk.StringVar()
        ttk.Entry(height_frame, textvariable=self.search_min_height_var, width=7).pack(side="left")
        ttk.Label(height_frame, text=" - ").pack(side="left")
        ttk.Entry(height_frame, textvariable=self.search_max_height_var, width=7).pack(side="left")

        ttk.Label(grid_frame, text="Aspect:", width=8, anchor="e").grid(row=1, column=4, sticky="e", padx=(0, 5), pady=4)
        self.search_aspect_var = tk.StringVar(value="Any")
        ttk.Combobox(grid_frame, textvariable=self.search_aspect_var,
                     values=["Any", "Landscape", "Portrait", "Square"],
                     state="readonly", width=12).grid(row=1, column=5, sticky="w", pady=4)

        # Row 2: Size preset / Caption / Vision status
        ttk.Label(grid_frame, text="Size:", width=8, anchor="e").grid(row=2, column=0, sticky="e", padx=(0, 5), pady=4)
        self.search_size_preset_var = tk.StringVar(value="Any")
        size_combo = ttk.Combobox(grid_frame, textvariable=self.search_size_preset_var,
                     values=["Any", "Small (<500px)", "Medium (500-1500px)", "Large (>1500px)", "HD (>1920px)", "4K (>3840px)"],
                     state="readonly", width=18)
        size_combo.grid(row=2, column=1, sticky="w", padx=(0, 15), pady=4)
        size_combo.bind("<<ComboboxSelected>>", self._apply_size_preset)

        ttk.Label(grid_frame, text="Caption:", width=8, anchor="e").grid(row=2, column=2, sticky="e", padx=(0, 5), pady=4)
        self.search_has_caption_var = tk.StringVar(value="Any")
        ttk.Combobox(grid_frame, textvariable=self.search_has_caption_var,
                     values=["Any", "Yes", "No", "Short (<50 chars)"],
                     state="readonly", width=14).grid(row=2, column=3, sticky="w", padx=(0, 15), pady=4)

        ttk.Label(grid_frame, text="Vision:", width=8, anchor="e").grid(row=2, column=4, sticky="e", padx=(0, 5), pady=4)
        self.search_vision_var = tk.StringVar(value="All")
        ttk.Combobox(grid_frame, textvariable=self.search_vision_var,
                     values=["All", "Processed", "Not processed"],
                     state="readonly", width=12).grid(row=2, column=5, sticky="w", pady=4)

        # Hidden type var for compatibility
        self.search_type_var = tk.StringVar(value="All")

        # Row 3: Hint and Search button
        bottom_frame = ttk.Frame(self.advanced_search_frame)
        bottom_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        bottom_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(bottom_frame, text="Tip: Separate multiple search terms with spaces",
                  style="Hint.TLabel").grid(row=0, column=0, sticky="w")

        ttk.Button(bottom_frame, text="Search", style="Small.Primary.TButton",
                   command=self._apply_filter, width=10).grid(row=0, column=1, sticky="e")

    def _apply_size_preset(self, event=None):
        """Apply dimension presets based on size selection."""
        preset = self.search_size_preset_var.get()
        # Clear existing
        self.search_min_width_var.set("")
        self.search_max_width_var.set("")
        self.search_min_height_var.set("")
        self.search_max_height_var.set("")

        if preset == "Small (<500px)":
            self.search_max_width_var.set("500")
            self.search_max_height_var.set("500")
        elif preset == "Medium (500-1500px)":
            self.search_min_width_var.set("500")
            self.search_max_width_var.set("1500")
        elif preset == "Large (>1500px)":
            self.search_min_width_var.set("1500")
        elif preset == "HD (>1920px)":
            self.search_min_width_var.set("1920")
        elif preset == "4K (>3840px)":
            self.search_min_width_var.set("3840")

    def _clear_all_filters(self):
        """Clear all search filters and show all images."""
        self.filter_var.set("")
        if hasattr(self, 'search_include_var'):
            self.search_include_var.set("")
        if hasattr(self, 'search_exclude_var'):
            self.search_exclude_var.set("")
        if hasattr(self, 'search_source_var'):
            self.search_source_var.set("All")
        if hasattr(self, 'search_vision_var'):
            self.search_vision_var.set("All")
        if hasattr(self, 'search_type_var'):
            self.search_type_var.set("All")
        if hasattr(self, 'search_min_width_var'):
            self.search_min_width_var.set("")
        if hasattr(self, 'search_max_width_var'):
            self.search_max_width_var.set("")
        if hasattr(self, 'search_min_height_var'):
            self.search_min_height_var.set("")
        if hasattr(self, 'search_max_height_var'):
            self.search_max_height_var.set("")
        if hasattr(self, 'search_aspect_var'):
            self.search_aspect_var.set("Any")
        if hasattr(self, 'search_size_preset_var'):
            self.search_size_preset_var.set("Any")
        if hasattr(self, 'search_has_caption_var'):
            self.search_has_caption_var.set("Any")
        self._load_all_images_async()

    def _apply_filter(self):
        self.gallery_status.set("Filtering...")

        def filter_thread():
            all_images = self.manager.get_all_images()

            # Pre-parse tags for all images
            for img in all_images:
                if img.get("tags") and isinstance(img["tags"], str):
                    try:
                        img["_tags_parsed"] = " ".join(json.loads(img["tags"])).lower()
                    except:
                        img["_tags_parsed"] = ""
                else:
                    img["_tags_parsed"] = ""

            # Gather all filter criteria
            simple_text = self.filter_var.get().strip()
            if simple_text.startswith("Search saved"):
                simple_text = ""

            include_text = getattr(self, 'search_include_var', tk.StringVar()).get().strip().lower()
            exclude_text = getattr(self, 'search_exclude_var', tk.StringVar()).get().strip().lower()
            source_filter = getattr(self, 'search_source_var', tk.StringVar()).get()
            vision_filter = getattr(self, 'search_vision_var', tk.StringVar()).get()
            type_filter = getattr(self, 'search_type_var', tk.StringVar()).get()
            aspect_filter = getattr(self, 'search_aspect_var', tk.StringVar()).get()
            caption_filter = getattr(self, 'search_has_caption_var', tk.StringVar()).get()

            # Dimension filters
            try:
                min_width = int(getattr(self, 'search_min_width_var', tk.StringVar()).get()) if getattr(self, 'search_min_width_var', tk.StringVar()).get() else 0
            except:
                min_width = 0
            try:
                max_width = int(getattr(self, 'search_max_width_var', tk.StringVar()).get()) if getattr(self, 'search_max_width_var', tk.StringVar()).get() else 999999
            except:
                max_width = 999999
            try:
                min_height = int(getattr(self, 'search_min_height_var', tk.StringVar()).get()) if getattr(self, 'search_min_height_var', tk.StringVar()).get() else 0
            except:
                min_height = 0
            try:
                max_height = int(getattr(self, 'search_max_height_var', tk.StringVar()).get()) if getattr(self, 'search_max_height_var', tk.StringVar()).get() else 999999
            except:
                max_height = 999999

            # Check if any filters are active
            has_filters = (
                simple_text or include_text or exclude_text or
                source_filter != "All" or vision_filter != "All" or
                type_filter != "All" or aspect_filter != "Any" or
                caption_filter != "Any" or
                min_width > 0 or max_width < 999999 or
                min_height > 0 or max_height < 999999
            )

            if not has_filters:
                # No filters - show all
                self.parent_container.after(0, lambda: self._finish_filter(all_images, f"{len(all_images)} saved images"))
                return

            # Parse include/exclude terms
            include_terms = include_text.split() if include_text else []
            exclude_terms = exclude_text.split() if exclude_text else []
            simple_terms = simple_text.lower().split() if simple_text else []

            def image_matches(img):
                # Build searchable text
                searchable = " ".join([
                    img.get("query", "").lower(),
                    img.get("source", "").lower(),
                    img.get("filename", "").lower(),
                    (img.get("alt") or "").lower(),
                    img.get("_tags_parsed", "")
                ])

                # Simple text filter (all terms must match)
                for term in simple_terms:
                    if term not in searchable:
                        return False

                # Include filter (all terms must match)
                for term in include_terms:
                    if term not in searchable:
                        return False

                # Exclude filter (none of the terms should match)
                for term in exclude_terms:
                    if term in searchable:
                        return False

                # Source filter
                if source_filter != "All":
                    if img.get("source", "") != source_filter:
                        return False

                # Vision processed filter
                if vision_filter == "Processed":
                    if not img.get("vision_processed"):
                        return False
                elif vision_filter == "Not processed":
                    if img.get("vision_processed"):
                        return False

                # Type filter (full image vs thumbnail only)
                if type_filter == "Full images":
                    if img.get("preview_only"):
                        return False
                elif type_filter == "Thumbnails only":
                    if not img.get("preview_only"):
                        return False

                # Dimension filters
                width = img.get("width", 0) or 0
                height = img.get("height", 0) or 0

                if width < min_width or width > max_width:
                    return False
                if height < min_height or height > max_height:
                    return False

                # Aspect ratio filter
                if aspect_filter != "Any" and width > 0 and height > 0:
                    ratio = width / height
                    if aspect_filter == "Landscape" and ratio <= 1.1:
                        return False
                    elif aspect_filter == "Portrait" and ratio >= 0.9:
                        return False
                    elif aspect_filter == "Square" and (ratio < 0.9 or ratio > 1.1):
                        return False

                # Caption filter
                caption = img.get("alt") or ""
                if caption_filter == "Yes":
                    if not caption or len(caption) < 5:
                        return False
                elif caption_filter == "No":
                    if caption and len(caption) >= 5:
                        return False
                elif caption_filter == "Short (<50 chars)":
                    if not caption or len(caption) >= 50:
                        return False

                return True

            filtered = [img for img in all_images if image_matches(img)]

            # Build result message
            filter_parts = []
            if simple_text:
                filter_parts.append(f"'{simple_text}'")
            if include_text:
                filter_parts.append(f"include:{include_text}")
            if exclude_text:
                filter_parts.append(f"exclude:{exclude_text}")
            if source_filter != "All":
                filter_parts.append(source_filter)
            if vision_filter != "All":
                filter_parts.append(vision_filter.lower())

            if filter_parts:
                result_msg = f"{len(filtered)} images ({', '.join(filter_parts[:3])})"
            else:
                result_msg = f"{len(filtered)} images matching filters"

            self.parent_container.after(0, lambda: self._finish_filter(filtered, result_msg))

        threading.Thread(target=filter_thread, daemon=True).start()

    def _finish_filter(self, filtered_images, result_msg):
        """Update UI after filtering completes."""
        self.all_images = filtered_images
        self.gallery_status.set(result_msg)
        self.canvas.yview_moveto(0)  # Scroll to top
        self._update_visible_cards_chunked()

    def _update_visible_cards(self):
        """Called when filter/data changes - refresh the display."""
        self._update_visible_cards_chunked()

    def _create_card_widget(self):
        card = tk.Frame(
            self.gallery_frame,
            bg=theme.get_color("bg_main"),
            highlightthickness=3,
            highlightbackground=theme.get_color("bg_main"),
            highlightcolor=theme.get_color("bg_main"),
            padx=6,
            pady=6
        )
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)

        img_label = ttk.Label(card, background=theme.get_color("bg_card"))
        img_label.grid(row=0, column=0, sticky="nsew")

        check_label = tk.Label(
            card,
            text="✓",
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg=theme.get_color("accent"),
            padx=4,
            pady=2
        )
        check_label.place(x=4, y=4)
        check_label.place_forget()

        info_frame = ttk.Frame(card)
        info_frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        source_label = ttk.Label(info_frame, font=("Helvetica", 10, "bold"), foreground=theme.get_color("accent"))
        source_label.pack(anchor="w")

        tags_label = ttk.Label(info_frame, font=("Helvetica", 9), foreground=theme.get_color("text_primary"), wraplength=140)
        tags_label.pack(anchor="w")

        card.img_label = img_label
        card.check_label = check_label
        card.source_label = source_label
        card.tags_label = tags_label

        self.card_pool.append(card)

    def _start_search(self):
        # Prevent double-start
        if self._download_in_progress:
            self.search_status.set("Download already in progress...")
            return

        query = self.query_var.get().strip()
        if not query or query == "Enter search term and press Enter":
            return

        sources = {s: self.limits[s].get() for s, v in self.sources.items() if v.get()}

        if not sources:
            self.search_status.set("No sources selected")
            return

        total_pages = sum(sources.values())
        self.search_status.set(f"Searching '{query}' - fetching {total_pages} page{'s' if total_pages != 1 else ''}...")

        def run():
            future = self.manager.schedule(self.manager.search_all(query, sources))
            if future:
                future.add_done_callback(lambda f: self.right_panel.after(0, lambda: self._on_search_done(f.result())))

        threading.Thread(target=run, daemon=True).start()

    def _on_search_done(self, results):
        if not results:
            self.search_status.set("No images found")
            self._download_in_progress = False
            self._load_all_images_async()
            return

        total = len(results)
        preview_mode = self.preview_mode_var.get()
        status = f"Found {total} images - creating thumbnails"
        if not preview_mode:
            status += " + downloading full images"
        self.search_status.set(f"Processing 0/{total} images...")
        self._download_in_progress = True
        self._stop_download_requested = False

        # Update button to show stop option
        self.add_images_btn.config(text="Stop Downloads", style="Small.Danger.TButton")

        async def download():
            import aiohttp
            import asyncio
            sem = self.manager.get_semaphore(50)
            async with aiohttp.ClientSession() as sess:
                downloaded = 0

                async def download_one(item):
                    nonlocal downloaded
                    if self._stop_download_requested:
                        return None
                    result = await self.manager.download_and_save(
                        sess,
                        item["url"],
                        item["tags"],
                        item["source"],
                        item["query"],
                        item.get("alt", ""),
                        preview_only=preview_mode
                    )
                    if result:
                        downloaded += 1
                    self.right_panel.after(0, lambda d=downloaded, t=total: self.search_status.set(f"Processing {d}/{t} images..."))
                    return result

                async def limited_download(item):
                    async with sem:
                        return await download_one(item)

                tasks = [limited_download(item) for item in results]
                await asyncio.gather(*tasks, return_exceptions=True)

                if self._stop_download_requested:
                    final_msg = f"Stopped - Downloaded {downloaded}/{total} images"
                elif downloaded == total:
                    final_msg = f"Download complete! {downloaded} images saved"
                elif downloaded == 0:
                    final_msg = "No images were saved (possible errors or duplicates)"
                else:
                    final_msg = f"Downloaded {downloaded}/{total} images"

                self._download_in_progress = False
                self._stop_download_requested = False
                self.right_panel.after(0, lambda msg=final_msg: self.search_status.set(msg))
                self.right_panel.after(0, self._reset_download_button)
                self.right_panel.after(0, self._load_all_images)

        def run():
            try:
                future = self.manager.schedule(download())
                if future:
                    future.result()  # Wait for completion
            except Exception as e:
                logger.error(f"[SEARCH DOWNLOAD ERROR] {e}")
            finally:
                self._download_in_progress = False
                self._stop_download_requested = False
                self.right_panel.after(0, self._reset_download_button)

        threading.Thread(target=run, daemon=True).start()

    def _toggle_manual_download(self):
        """Toggle between starting and stopping downloads."""
        if self._download_in_progress:
            self._stop_manual_download()
        else:
            self._add_manual_images()

    def _stop_manual_download(self):
        """Request stop of ongoing download."""
        if not self._download_in_progress:
            return
        self._stop_download_requested = True
        self.search_status.set("Stopping downloads...")
        self.add_images_btn.config(text="Stopping...", state="disabled")

    def _reset_download_button(self):
        """Reset download button to normal state."""
        self.add_images_btn.config(text="Add Images (URLs)", state="normal", style="Small.Primary.TButton")

    def _add_manual_images(self):
        urls_text = self.url_text.get("1.0", "end").strip()
        if not urls_text or urls_text.startswith("#"):
            self.search_status.set("Please paste at least one URL")
            return

        urls = [line.strip() for line in urls_text.splitlines() if line.strip() and not line.startswith("#")]
        if not urls:
            self.search_status.set("No valid URLs found")
            return

        self._download_in_progress = True
        self._stop_download_requested = False

        # Update button to show stop option
        self.add_images_btn.config(text="Stop Downloads", style="Small.Danger.TButton")

        query = self.manual_query_var.get().strip() or "manual"
        source = self.manual_source_var.get().strip() or "Manual"
        tags = [t.strip() for t in self.manual_tags_var.get().split(",") if t.strip()]
        alt = self.manual_alt_var.get().strip()

        preview_only = not self.manual_full_download_var.get()

        total = len(urls)
        self.search_status.set(f"Processing 0/{total} images...")

        async def process():
            import aiohttp
            import asyncio
            sem = self.manager.get_semaphore(50)
            async with aiohttp.ClientSession() as sess:
                downloaded = 0
                skipped = 0

                async def download_one(url):
                    nonlocal downloaded, skipped
                    # Check if stop was requested
                    if self._stop_download_requested:
                        skipped += 1
                        return None
                    result = await self.manager.download_and_save(
                        sess, url, tags, source, query, alt, preview_only=preview_only
                    )
                    if result:
                        downloaded += 1
                    self.right_panel.after(0, lambda d=downloaded, t=total: self.search_status.set(f"Processing {d}/{t} images..."))
                    return result

                async def limited_download(url):
                    async with sem:
                        return await download_one(url)

                concurrent_tasks = [limited_download(url) for url in urls]
                await asyncio.gather(*concurrent_tasks, return_exceptions=True)

                # Build final message
                if self._stop_download_requested:
                    final_msg = f"Stopped - Downloaded {downloaded}/{total} images"
                elif downloaded == total:
                    final_msg = f"Download complete! {downloaded} images saved"
                elif downloaded == 0:
                    final_msg = "No images were saved (possible errors or duplicates)"
                else:
                    final_msg = f"Downloaded {downloaded}/{total} images"

                self._download_in_progress = False
                self._stop_download_requested = False
                self.right_panel.after(0, lambda msg=final_msg: self.search_status.set(msg))
                self.right_panel.after(0, self._reset_download_button)
                self.right_panel.after(0, self._load_all_images)

        def run():
            try:
                future = self.manager.schedule(process())
                if future:
                    future.result()  # Wait for completion
            except Exception as e:
                logger.error(f"[DOWNLOAD ERROR] {e}")
            finally:
                self._download_in_progress = False
                self._stop_download_requested = False
                self.right_panel.after(0, self._reset_download_button)

        threading.Thread(target=run, daemon=True).start()

    def _add_local_images(self):
        from tkinter import filedialog

        file_paths = filedialog.askopenfilenames(
            title="Select Local Images to Add",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff"),
                ("All files", "*.*")
            ]
        )
        if not file_paths:
            return

        total = len(file_paths)
        query = self.manual_query_var.get().strip() or "local"
        source = self.manual_source_var.get().strip() or "Local"
        tags = [t.strip() for t in self.manual_tags_var.get().split(",") if t.strip()]
        alt = self.manual_alt_var.get().strip()
        copy_full = self.manual_full_download_var.get()

        self.search_status.set(f"Processing 0/{total} local images...")

        async def process_local():
            import asyncio
            sem = self.manager.get_semaphore(60)
            processed = 0

            async def handle_one(filepath):
                nonlocal processed
                try:
                    img = Image.open(filepath)
                    img.load()
                    width, height = img.size
                    img_rgb = img.convert("RGB")

                    thumb_img = img_rgb.copy()
                    thumb_img.thumbnail((300, 300))
                    thumb_filename = f"thumb_{uuid.uuid4().hex[:12]}.jpg"
                    thumb_path = THUMBS_DIR / thumb_filename
                    thumb_img.save(thumb_path, "JPEG", quality=85, optimize=True)
                    thumb_rel_path = f"images/thumbs/{thumb_filename}"

                    original_path = ""
                    filename = os.path.basename(filepath)
                    if copy_full:
                        ext = ".jpg" if filename.lower().endswith(('.jpg', '.jpeg')) else ".png"
                        new_filename = self.manager.generate_filename(tags, width, height, ext)
                        dest_path = ORIGINALS_DIR / new_filename
                        img_rgb.save(dest_path, "JPEG" if ext == ".jpg" else "PNG", quality=95)
                        original_path = f"images/originals/{new_filename}"
                        filename = new_filename

                    metadata = {
                        "id": str(uuid.uuid4()),
                        "filename": filename,
                        "path": original_path,
                        "thumb_path": thumb_rel_path,
                        "url": f"file://{filepath}",
                        "source": source,
                        "query": query,
                        "width": width,
                        "height": height,
                        "alt": alt,
                        "tags": json.dumps(tags),
                        "preview_only": 0 if copy_full else 1
                    }

                    # Insert into database (thread-safe with check_same_thread=False)
                    try:
                        with self.manager.conn:
                            self.manager.conn.execute("""
                                INSERT OR IGNORE INTO images
                                (id, filename, path, thumb_path, url, source, query, width, height, alt, tags, preview_only)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                metadata['id'], metadata['filename'], metadata['path'],
                                metadata['thumb_path'], metadata['url'], metadata['source'],
                                metadata['query'], metadata['width'], metadata['height'],
                                metadata['alt'], metadata['tags'], metadata['preview_only']
                            ))
                        self.manager.existing_urls.add(metadata['url'])
                    except Exception:
                        pass

                    processed += 1
                    self.right_panel.after(0, lambda p=processed: self.search_status.set(f"Processing {p}/{total} local images..."))

                except Exception as e:
                    logger.error(f"[LOCAL IMAGE ERROR] {filepath}: {e}")

            async def limited_handle(path):
                async with sem:
                    await handle_one(path)

            tasks = [limited_handle(p) for p in file_paths]
            await asyncio.gather(*tasks, return_exceptions=True)

            final_msg = f"Added {processed}/{total} local images"
            self.right_panel.after(0, lambda: self.search_status.set(final_msg))
            self.right_panel.after(0, self._load_all_images)

        def run():
            future = self.manager.schedule(process_local())
            if future:
                future.add_done_callback(lambda f: None)

        threading.Thread(target=run, daemon=True).start()

    def _load_vision_instances(self):
        count = self.vision_count_var.get()
        if count < 1:
            return

        self.target_instance_count = count
        self.loaded_instance_count = 0

        self.load_vision_btn.config(text="Loading...", state="disabled")
        self.vision_status_var.set("Loading instances...")
        self.unload_btn.config(state="disabled")

        device_str = self.vision_device_var.get()

        if device_str == "CPU":
            device_spec = "cpu"
        else:
            try:
                gpu_idx = int(device_str.split("GPU ")[1].split(":")[0])
                device_spec = gpu_idx
            except:
                device_spec = "cpu"

        def load_thread():
            from core.vision_manager import VisionManager
            registry = self.vision_registry

            for _ in range(count):
                manager = VisionManager(root=self.right_panel.winfo_toplevel())
                manager.on_loaded_callback = self._on_single_vision_loaded
                manager.on_error_callback = lambda msg: logger.error(f"[VISION ERROR] {msg}")
                manager.load(device_spec)
                registry.add(manager)

        threading.Thread(target=load_thread, daemon=True).start()

    def _on_single_vision_loaded(self):
        self.loaded_instance_count += 1

        current = self.loaded_instance_count
        target = self.target_instance_count

        if current < target:
            self.vision_status_var.set(f"Loading {current}/{target} instances...")
        else:
            self.load_vision_btn.config(text="Load Instances", state="normal")
            self.vision_status_var.set(f"Florence-2: {target} instance{'s' if target != 1 else ''} loaded")
            self.unload_btn.config(state="normal")

        self._update_vision_status()

    def _unload_all_vision(self):
        self.vision_registry.unload_all()
        self.target_instance_count = 0
        self.loaded_instance_count = 0
        self._update_vision_status()

    def _update_vision_status(self):
        count = self.vision_registry.get_count()
        plural = "s" if count != 1 else ""
        self.vision_status_var.set(f"Florence-2: {count} instance{plural} loaded")

        # Update unload button state
        if count == 0:
            self.unload_btn.config(state="disabled")
            self.auto_load_btn.config(state="normal", text="Auto Load (Recommended)")
        else:
            self.unload_btn.config(state="normal")
            self.auto_load_btn.config(state="normal", text="Auto Load (Recommended)")

    def _toggle_advanced_vision(self):
        """Show or hide the advanced vision options."""
        if self.show_advanced_var.get():
            self.advanced_frame.grid()
        else:
            self.advanced_frame.grid_remove()

    def _auto_load_vision(self):
        """Auto-detect GPUs and load optimal Florence-2 instances based on settings."""
        from core import system_monitor

        self.auto_load_btn.config(text="Detecting...", state="disabled")
        self.vision_status_var.set("Detecting hardware...")

        def detect_and_load():
            # Load settings
            settings = load_vision_settings()
            strategy = settings["vision_gpu_strategy"]
            max_per_gpu = settings["vision_max_per_gpu"]
            max_total = settings["vision_max_total"]
            reserved_vram = settings["vision_reserved_vram"]
            allow_cpu = settings["vision_allow_cpu"]
            cpu_instances = settings["vision_cpu_instances"]
            gpu_enabled = settings["vision_gpu_enabled"]
            gpu_instances = settings["vision_gpu_instances"]

            gpu_count = system_monitor.get_gpu_count()

            # Build load plan: list of (device, instance_count, device_name)
            load_plan = []
            is_cpu_only = False

            if strategy == "cpu_only":
                # Force CPU mode
                is_cpu_only = True
                load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))
                logger.info(f"[AUTO LOAD] CPU-only mode: {cpu_instances} instance(s)")

            elif strategy == "specific":
                # Use only explicitly enabled GPUs with their specified instance counts
                for i in range(gpu_count):
                    if gpu_enabled.get(str(i), True):
                        stats = system_monitor.get_gpu_stats(i)
                        if stats:
                            count = min(gpu_instances.get(str(i), 2), max_per_gpu)
                            load_plan.append((i, count, stats["name"]))
                            logger.info(f"[AUTO LOAD] GPU {i} ({stats['name']}): {count} instance(s) (specific)")

                # Add CPU if enabled and no GPUs selected
                if not load_plan and allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))

            elif strategy == "all_gpus":
                # Distribute across ALL available GPUs
                for i in range(gpu_count):
                    stats = system_monitor.get_gpu_stats(i)
                    if stats:
                        available_vram = stats["vram_total_gb"] - stats["vram_used_gb"]
                        if available_vram >= 2.5:
                            usable_vram = available_vram - reserved_vram
                            count = max(1, min(max_per_gpu, int(usable_vram / 2.0)))
                            load_plan.append((i, count, stats["name"]))
                            logger.info(f"[AUTO LOAD] GPU {i} ({stats['name']}): {count} instance(s), {available_vram:.1f}GB free")

                # Fallback to CPU if no usable GPUs
                if not load_plan and allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))

            elif strategy == "single_best":
                # Use only the best GPU (most free VRAM)
                best_gpu_idx = -1
                best_vram = 0
                best_name = ""

                for i in range(gpu_count):
                    stats = system_monitor.get_gpu_stats(i)
                    if stats:
                        available_vram = stats["vram_total_gb"] - stats["vram_used_gb"]
                        if available_vram > best_vram:
                            best_vram = available_vram
                            best_gpu_idx = i
                            best_name = stats["name"]

                if best_gpu_idx >= 0 and best_vram >= 2.5:
                    usable_vram = best_vram - reserved_vram
                    count = max(1, min(max_per_gpu, int(usable_vram / 2.0)))
                    load_plan.append((best_gpu_idx, count, best_name))
                    logger.info(f"[AUTO LOAD] Best GPU {best_gpu_idx} ({best_name}): {count} instance(s), {best_vram:.1f}GB free")
                elif allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))

            else:  # "auto" - smart detection (default)
                # Find best GPU, or use all if multiple have good VRAM
                usable_gpus = []

                for i in range(gpu_count):
                    stats = system_monitor.get_gpu_stats(i)
                    if stats:
                        available_vram = stats["vram_total_gb"] - stats["vram_used_gb"]
                        if available_vram >= 2.5:
                            usable_vram = available_vram - reserved_vram
                            count = max(1, min(max_per_gpu, int(usable_vram / 2.0)))
                            usable_gpus.append((i, count, stats["name"], available_vram))

                if usable_gpus:
                    # Sort by free VRAM descending
                    usable_gpus.sort(key=lambda x: x[3], reverse=True)
                    # Use all usable GPUs in auto mode
                    for gpu_idx, count, name, vram in usable_gpus:
                        load_plan.append((gpu_idx, count, name))
                        logger.info(f"[AUTO LOAD] GPU {gpu_idx} ({name}): {count} instance(s), {vram:.1f}GB free")
                elif allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))
                    logger.info("[AUTO LOAD] No suitable GPUs, using CPU")

            # Enforce max_total limit
            total_instances = sum(p[1] for p in load_plan)
            if total_instances > max_total:
                # Scale down proportionally
                scale = max_total / total_instances
                load_plan = [(dev, max(1, int(cnt * scale)), name) for dev, cnt, name in load_plan]
                total_instances = sum(p[1] for p in load_plan)

            if not load_plan:
                self.right_panel.after(0, lambda: self._auto_load_failed("No GPU or CPU available"))
                return

            # Update UI and start loading
            def start_loading():
                total = sum(p[1] for p in load_plan)
                self.target_instance_count = total
                self.loaded_instance_count = 0
                self._is_cpu_mode = is_cpu_only
                self._load_plan = load_plan

                if is_cpu_only:
                    msg = f"Loading {total} CPU instance(s) (slower mode)..."
                elif len(load_plan) == 1:
                    _, count, name = load_plan[0]
                    msg = f"Loading {count} instance{'s' if count > 1 else ''} on {name}..."
                else:
                    gpu_names = [p[2] for p in load_plan if p[0] != "cpu"]
                    msg = f"Loading {total} instances across {len(gpu_names)} GPUs..."

                self.vision_status_var.set(msg)
                self.auto_load_btn.config(text="Loading...")

                # Load instances according to plan
                from core.vision_manager import VisionManager
                registry = self.vision_registry

                for device, count, name in load_plan:
                    for _ in range(count):
                        manager = VisionManager(root=self.right_panel.winfo_toplevel())
                        manager.on_loaded_callback = self._on_auto_load_instance_ready
                        manager.on_error_callback = lambda msg: logger.error(f"[VISION ERROR] {msg}")
                        manager.load(device)
                        registry.add(manager)

            self.right_panel.after(0, start_loading)

        threading.Thread(target=detect_and_load, daemon=True).start()

    def _auto_load_failed(self, message: str):
        """Handle auto-load failure."""
        self.auto_load_btn.config(text="Auto Load (Recommended)", state="normal")
        self.vision_status_var.set(f"Load failed: {message}")

    def _on_auto_load_instance_ready(self):
        """Called when an auto-loaded instance is ready."""
        self.loaded_instance_count += 1

        current = self.loaded_instance_count
        target = self.target_instance_count

        if current < target:
            self.vision_status_var.set(f"Loading {current}/{target} instances...")
        else:
            self.auto_load_btn.config(text="Auto Load (Recommended)", state="normal")

            # Show appropriate message based on load plan
            is_cpu = getattr(self, '_is_cpu_mode', False)
            load_plan = getattr(self, '_load_plan', [])

            if is_cpu:
                self.vision_status_var.set("Florence-2: Ready (CPU mode - slower)")
            elif len(load_plan) == 1:
                _, count, name = load_plan[0]
                # Shorten name
                for prefix in ["NVIDIA GeForce ", "NVIDIA ", "GeForce "]:
                    if name.startswith(prefix):
                        name = name[len(prefix):]
                        break
                self.vision_status_var.set(f"Florence-2: {count} on {name}")
            elif len(load_plan) > 1:
                gpu_count = len([p for p in load_plan if p[0] != "cpu"])
                self.vision_status_var.set(f"Florence-2: {target} instances across {gpu_count} GPUs")
            else:
                self.vision_status_var.set(f"Florence-2: {target} instance{'s' if target != 1 else ''} ready")

            self.unload_btn.config(state="normal")

            # Check if analysis was pending (auto-load on analyze)
            if getattr(self, '_pending_analysis_after_load', False):
                self._pending_analysis_after_load = False
                # Small delay to let UI update, then start analysis
                self.right_panel.after(100, self._start_vision_analysis)

    def _start_vision_analysis(self):
        instances = self.vision_registry.instances
        if not instances:
            # Check if auto-load on analyze is enabled
            settings = load_vision_settings()
            if settings.get("vision_auto_load", True):
                # Auto-load first, then start analysis
                self.vision_status_var.set("Auto-loading vision instances...")
                self._pending_analysis_after_load = True
                self._auto_load_vision()
                return
            else:
                self.vision_status_var.set("No Florence-2 instances loaded")
                return

        if self.analysis_running:
            return

        self.analysis_running = True
        self.stop_analysis_requested = False

        self.analyze_btn.config(text="Analyzing...", state="disabled")
        self.stop_btn.grid()  # Show the stop button
        self.stop_btn.config(state="normal")
        self.vision_status_var.set("Preparing analysis...")

        def run_analysis():
            self._vision_worker()

        threading.Thread(target=run_analysis, daemon=True).start()

    def _vision_worker(self):
        instances = [mgr for mgr in self.vision_registry.instances if mgr.is_loaded()]
        if not instances:
            self.right_panel.after(0, lambda: self._end_analysis("No Florence-2 instances loaded"))
            return

        project_root = Path(__file__).parent.parent
        unprocessed = []

        all_images = self.manager.get_all_images()

        for img in all_images:
            if self.stop_analysis_requested:
                self.right_panel.after(0, lambda: self._end_analysis("Analysis stopped by user"))
                return

            if img["vision_processed"]:
                should_reprocess = False

                if self.override_short_caption_var.get():
                    caption = img.get("alt") or ""
                    if len(caption) < 50:
                        should_reprocess = True

                if self.override_few_tags_var.get():
                    tags_str = img.get("tags") or "[]"
                    try:
                        tags = json.loads(tags_str)
                        if len(tags) <= 1:
                            should_reprocess = True
                    except:
                        should_reprocess = True

                if not should_reprocess:
                    continue

            source_match = (
                (img["source"] == "Pixabay" and self.filter_pixabay_var.get()) or
                (img["source"] == "Pexels" and self.filter_pexels_var.get()) or
                (img["source"] == "Unsplash" and self.filter_unsplash_var.get()) or
                (img["source"] in ("Manual", "URL") and self.filter_url_var.get()) or
                (img["source"] in ("Local", "Chat") and self.filter_uploaded_var.get())
            )
            if not source_match:
                continue

            path = None
            if img["path"]:
                p = project_root / img["path"]
                if p.exists():
                    path = str(p)
            elif img["thumb_path"]:
                p = project_root / img["thumb_path"]
                if p.exists():
                    path = str(p)

            if path:
                unprocessed.append((img["id"], path))

        total = len(unprocessed)
        if total == 0:
            self.right_panel.after(0, lambda: self._end_analysis("No images to analyze (filtered or already processed)"))
            return

        self.right_panel.after(0, lambda: self.vision_status_var.set(f"Analyzing 0/{total} images..."))

        processed = 0

        def make_callback(img_id):
            def callback(result):
                nonlocal processed

                if self.stop_analysis_requested:
                    return

                if "error" in result:
                    logger.error(f"[VISION ERROR for image {img_id}] {result['error']}")

                if "analysis" in result:
                    caption = result["analysis"].get("caption", "")
                    objects = result["analysis"].get("objects", [])

                    update_fields = []
                    update_values = []

                    if self.apply_captions_var.get():
                        update_fields.append("alt = ?")
                        update_values.append(caption)

                    if self.apply_tags_var.get():
                        cur = self.manager.conn.execute("SELECT tags FROM images WHERE id = ?", (img_id,))
                        row = cur.fetchone()
                        existing = [t.lower() for t in json.loads(row[0])] if row and row[0] else []
                        merged = objects + [t for t in existing if t not in objects]
                        update_fields.append("tags = ?")
                        update_values.append(json.dumps(merged))

                    update_fields.append("vision_processed = 1")

                    if update_fields:
                        sql = f"UPDATE images SET {', '.join(update_fields)} WHERE id = ?"
                        update_values.append(img_id)
                        with self.manager.conn:
                            self.manager.conn.execute(sql, update_values)

                processed += 1
                self.right_panel.after(0, lambda p=processed: self.vision_status_var.set(f"Analyzing {p}/{total} images..."))

                if processed == total:
                    self.right_panel.after(0, lambda: self._end_analysis(f"Analysis complete! Processed {total} images."))

            return callback

        # Check if CPU mode - throttle to prevent overload
        is_cpu = getattr(self, '_is_cpu_mode', False)

        for idx, (img_id, path) in enumerate(unprocessed):
            if self.stop_analysis_requested:
                self.right_panel.after(0, lambda: self._end_analysis("Analysis stopped by user"))
                return

            manager = instances[idx % len(instances)]
            manager.send_analysis(
                image_path=path,
                callback=make_callback(img_id),
                need_objects=self.apply_tags_var.get()
            )

            # CPU throttle: don't queue too many requests at once
            # Send in small batches to keep system responsive
            if is_cpu and (idx + 1) % 3 == 0:
                time.sleep(0.5)  # Pause every 3 images

    def _toggle_analysis(self):
        if self.analysis_running:
            self._request_stop_analysis()
        else:
            self._start_vision_analysis()

    def _request_stop_analysis(self):
        if not self.analysis_running:
            return

        self.analysis_running = False
        self.stop_analysis_requested = True
        self._reset_analysis_buttons()
        self.vision_status_var.set("Stopping analysis...")

        for mgr in self.vision_registry.instances:
            mgr.pending_callbacks.clear()

        def unload_and_finish():
            self.vision_registry.unload_all()
            self.right_panel.after(0, self._on_stop_complete)

        threading.Thread(target=unload_and_finish, daemon=True).start()

    def _on_stop_complete(self):
        self.stop_analysis_requested = False
        self.vision_status_var.set("Analysis stopped - instances unloaded")
        self._update_vision_status()
        self._load_all_images_async()

    def _reset_analysis_buttons(self):
        self.analyze_btn.config(text="Analyze Saved Images", state="normal")
        self.stop_btn.config(state="disabled")
        self.stop_btn.grid_remove()  # Hide the stop button

    def _end_analysis(self, final_message: str):
        self.analysis_running = False
        self.stop_analysis_requested = False
        self._reset_analysis_buttons()
        self.vision_status_var.set(final_message)

        if "stopped" in final_message.lower():
            self._update_vision_status()

        self._load_all_images_async()

        # Auto-unload if enabled and analysis completed successfully
        if "complete" in final_message.lower():
            settings = load_vision_settings()
            if settings.get("vision_auto_unload", False):
                logger.info("[VISION] Auto-unloading instances after analysis")
                self.right_panel.after(500, self._unload_all_vision)
                self.right_panel.after(600, lambda: self.vision_status_var.set(
                    f"{final_message} (instances unloaded)"))

    def _get_cached_thumbnail(self, path, size=150):
        cache_key = f"{path}_{size}"

        if cache_key in self._thumb_cache:
            self._thumb_cache_order.remove(cache_key)
            self._thumb_cache_order.append(cache_key)
            return self._thumb_cache[cache_key]

        photo = self._create_square_thumbnail(path, size)

        self._thumb_cache[cache_key] = photo
        self._thumb_cache_order.append(cache_key)

        while len(self._thumb_cache_order) > self._thumb_cache_max:
            oldest_key = self._thumb_cache_order.pop(0)
            self._thumb_cache.pop(oldest_key, None)

        return photo

    def _create_square_thumbnail(self, path, size=150):
        from PIL import Image, ImageTk
        try:
            if path and os.path.exists(path):
                pil_img = Image.open(path)
            else:
                pil_img = Image.new("RGB", (size, size), "#e0e0e0")

            pil_img = pil_img.convert("RGB")
            pil_img.thumbnail((size * 2, size * 2))

            width, height = pil_img.size
            left = (width - size) // 2
            top = (height - size) // 2
            right = left + size
            bottom = top + size
            pil_img = pil_img.crop((left, top, right, bottom))

            photo = ImageTk.PhotoImage(pil_img)
            return photo
        except Exception as e:
            logger.error(f"[THUMB ERROR] {e}")
            placeholder = Image.new("RGB", (size, size), "#d0d0d0")
            return ImageTk.PhotoImage(placeholder)

    def _create_hover_popup(self):
        if self.hover_popup:
            return

        self.hover_popup = tk.Toplevel(self.right_panel)
        self.hover_popup.wm_overrideredirect(True)
        self.hover_popup.wm_geometry("+0+0")
        self.hover_popup.configure(background="#222222", padx=10, pady=10)

        self.popup_img_label = ttk.Label(self.hover_popup, background="#222222")
        self.popup_img_label.pack(anchor="center")

        self.popup_meta_label = ttk.Label(
            self.hover_popup,
            foreground="#ffffff",
            background="#222222",
            font=("Helvetica", 10),
            justify="left",
            wraplength=400
        )
        self.popup_meta_label.pack(anchor="w", pady=(8, 0))

        self.hover_popup.withdraw()

    def _show_hover(self, event, img_data):
        if self.current_hover_card == event.widget:
            return

        self._create_hover_popup()

        path = None
        if img_data.get("path"):
            path = os.path.join("images", "originals", img_data["filename"])
        elif img_data.get("thumb_path"):
            path = os.path.join("images", "thumbs", os.path.basename(img_data["thumb_path"]))

        try:
            from PIL import Image, ImageTk
            pil_img = Image.open(path) if path and os.path.exists(path) else Image.new("RGB", (600, 600), "#333333")
            pil_img.thumbnail((600, 600))
            self.hover_photo = ImageTk.PhotoImage(pil_img)
            self.popup_img_label.configure(image=self.hover_photo)
        except Exception:
            self.popup_img_label.configure(image="")

        lines = []
        if img_data.get("alt"):
            lines.append(f"Caption: {img_data['alt']}")
        lines.append(f"Source: {img_data['source']}")
        lines.append(f"Query: {img_data['query']}")
        lines.append(f"Size: {img_data['width']}x{img_data['height']}")

        if img_data.get("tags"):
            tags = json.loads(img_data["tags"])
            tags_str = ", ".join(tags[:20])
            if len(tags) > 20:
                tags_str += f"... (+{len(tags)-20} more)"
            lines.append(f"Tags: {tags_str}")

        has_url = bool(img_data.get("url", "").startswith("http"))
        has_local = bool(img_data.get("path"))
        src_type = "url / local" if has_url and has_local else "local" if has_local else "url"
        lines.append(f"Stored: {src_type}")

        self.popup_meta_label.configure(text="\n".join(lines))

        popup_w = 460
        popup_h = 560

        mouse_x = event.x_root
        mouse_y = event.y_root
        screen_w = self.right_panel.winfo_screenwidth()
        screen_h = self.right_panel.winfo_screenheight()

        x = mouse_x + 45
        y = mouse_y - popup_h // 2 + 50

        if x + popup_w > screen_w - 30:
            x = mouse_x - popup_w - 45

        if y + popup_h > screen_h - 50:
            y = mouse_y - popup_h - 70

        if y < 40:
            y = 40

        x = max(30, min(x, screen_w - popup_w - 30))

        self.hover_popup.wm_geometry(f"+{int(x)}+{int(y)}")
        self.hover_popup.deiconify()
        self.current_hover_card = event.widget

    def _hide_hover(self):
        if self.hover_popup:
            self.hover_popup.withdraw()
        self.current_hover_card = None

    # Multi-select functionality
    def _toggle_image_selection(self, image_id: str, card):
        if image_id in self.selected_images:
            self.selected_images.discard(image_id)
            self._update_card_selection_visual(card, False)
        else:
            self.selected_images.add(image_id)
            self._update_card_selection_visual(card, True)

        self._update_selection_ui()

    def _update_card_selection_visual(self, card, is_selected: bool):
        if is_selected:
            card.configure(
                highlightbackground=theme.get_color("accent"),
                highlightcolor=theme.get_color("accent")
            )
            card.check_label.place(x=4, y=4)
        else:
            card.configure(
                highlightbackground=theme.get_color("bg_main"),
                highlightcolor=theme.get_color("bg_main")
            )
            card.check_label.place_forget()

    def _update_selection_ui(self):
        count = len(self.selected_images)

        if count > 0:
            self.selection_label.configure(text=f"{count} selected")
            self.selection_label.pack(side="left", padx=(0, 10))
            self.clear_selection_btn.pack(side="left", padx=(0, 6))
            self.export_selected_btn.pack(side="left", padx=(0, 6))
            self.delete_selected_btn.pack(side="left")  # Far right, away from other buttons
            # Show the selection frame in the grid
            self.selection_frame.grid()
        else:
            self.selection_label.pack_forget()
            self.clear_selection_btn.pack_forget()
            self.export_selected_btn.pack_forget()
            self.delete_selected_btn.pack_forget()
            # Hide the selection frame from the grid to reclaim space
            self.selection_frame.grid_remove()

    def _clear_selection(self):
        self.selected_images.clear()
        self._update_selection_ui()
        self._update_visible_cards()

    def _delete_selected_images(self):
        count = len(self.selected_images)
        if count == 0:
            return

        image_ids = list(self.selected_images)
        deleted, failed = self.manager.delete_images(image_ids)

        self.selected_images.clear()
        self._update_selection_ui()

        self._thumb_cache.clear()
        self._thumb_cache_order.clear()

        self._load_all_images_async()

        if failed == 0:
            self.gallery_status.set(f"Deleted {deleted} image{'s' if deleted != 1 else ''}")
        else:
            self.gallery_status.set(f"Deleted {deleted}, {failed} failed")

    def _export_selected_images(self):
        """Export selected images to a user-chosen directory."""
        from tkinter import filedialog
        import shutil

        count = len(self.selected_images)
        if count == 0:
            return

        # Ask user for export directory
        export_dir = filedialog.askdirectory(
            title="Select Export Directory",
            mustexist=False
        )

        if not export_dir:
            return  # User cancelled

        export_path = Path(export_dir)

        # Create directory if it doesn't exist
        try:
            export_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.gallery_status.set(f"Error creating directory: {e}")
            return

        # Get image data for selected images
        image_ids = list(self.selected_images)
        exported = 0
        failed = 0
        urls_list = []
        paths_list = []

        for img_id in image_ids:
            # Find image data
            img_data = None
            for img in self.all_images:
                if img.get("id") == img_id:
                    img_data = img
                    break

            if not img_data:
                failed += 1
                continue

            # Get original file path
            filename = img_data.get("filename", "")
            if not filename:
                failed += 1
                continue

            original_path = ORIGINALS_DIR / filename
            if not original_path.exists():
                failed += 1
                continue

            # Copy image file
            try:
                dest_path = export_path / filename
                shutil.copy2(original_path, dest_path)
                exported += 1

                # Collect URL and path info
                url = img_data.get("url", "")
                if url:
                    urls_list.append(f"{filename}: {url}")

                paths_list.append(f"{filename}: {original_path}")

            except Exception as e:
                logger.error(f"[EXPORT] Failed to copy {filename}: {e}")
                failed += 1

        # Write URLs file
        if urls_list:
            urls_file = export_path / "_image_urls.txt"
            try:
                with open(urls_file, "w", encoding="utf-8") as f:
                    f.write("Image Source URLs\n")
                    f.write("=" * 50 + "\n\n")
                    for line in urls_list:
                        f.write(line + "\n")
            except Exception as e:
                logger.error(f"[EXPORT] Failed to write URLs file: {e}")

        # Write source paths file
        if paths_list:
            paths_file = export_path / "_source_paths.txt"
            try:
                with open(paths_file, "w", encoding="utf-8") as f:
                    f.write("Original Image Paths (in ImageBuddy)\n")
                    f.write("=" * 50 + "\n\n")
                    for line in paths_list:
                        f.write(line + "\n")
            except Exception as e:
                logger.error(f"[EXPORT] Failed to write paths file: {e}")

        # Update status
        if failed == 0:
            self.gallery_status.set(f"Exported {exported} image{'s' if exported != 1 else ''} to {export_path.name}")
        else:
            self.gallery_status.set(f"Exported {exported}, {failed} failed")

        # Ask if user wants to open the folder
        self._open_export_folder(export_path)

    def _open_export_folder(self, folder_path):
        """Open the export folder in file explorer."""
        import subprocess
        import sys

        try:
            if sys.platform == 'win32':
                os.startfile(folder_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', folder_path])
            else:
                subprocess.run(['xdg-open', folder_path])
        except Exception as e:
            logger.error(f"[EXPORT] Failed to open folder: {e}")
