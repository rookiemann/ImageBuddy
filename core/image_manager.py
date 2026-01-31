# core/image_manager.py
import os, warnings
import io, hashlib
import json
import uuid
import threading
import asyncio
import aiohttp
from pathlib import Path
from PIL import Image
import sqlite3
from config import PIXABAY_KEY, PEXELS_KEY, UNSPLASH_KEY
from core import logger

PROJECT_ROOT = Path(__file__).parent.parent
IMAGES_DIR = PROJECT_ROOT / "images"
ORIGINALS_DIR = IMAGES_DIR / "originals"
THUMBS_DIR = IMAGES_DIR / "thumbs"
DB_PATH = IMAGES_DIR / "images.db"

# Ensure directories exist
IMAGES_DIR.mkdir(exist_ok=True)
ORIGINALS_DIR.mkdir(exist_ok=True)
THUMBS_DIR.mkdir(exist_ok=True)


class ImageManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._shutting_down = False

        # Database connection (thread-safe reads allowed)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.row_factory = sqlite3.Row

        self._create_table_and_migrate()

        # Load duplicate-tracking sets
        self.existing_urls = self._load_existing_urls()

        # Background async loop for concurrent downloads/processing
        self.loop = None
        self.thread = threading.Thread(target=self._start_background_loop, daemon=True)
        self.thread.start()

    def _create_table_and_migrate(self):
        """Create table and safely add new columns if they don't exist."""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY,
                    filename TEXT,
                    path TEXT,
                    thumb_path TEXT,
                    url TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    query TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    alt TEXT,
                    tags TEXT,
                    preview_only INTEGER DEFAULT 0,
                    downloaded_at TEXT DEFAULT (datetime('now')),
                    vision_processed INTEGER DEFAULT 0
                )
            """)

            # Ensure unique index on url
            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_url ON images(url);")

            # Add vision_processed flag if missing
            try:
                self.conn.execute("ALTER TABLE images ADD COLUMN vision_processed INTEGER DEFAULT 0")
                logger.info("[DB MIGRATION] Added vision_processed flag")
            except sqlite3.OperationalError:
                pass  # Already exists

            # Table to track deleted URLs (prevents re-downloading)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS blocked_urls (
                    url TEXT PRIMARY KEY,
                    source TEXT,
                    deleted_at TEXT DEFAULT (datetime('now'))
                )
            """)

    def _load_existing_urls(self) -> set[str]:
        """Load all existing URLs for fast duplicate checking (includes blocked URLs)."""
        urls = set()

        # Load URLs from images table
        cur = self.conn.execute("SELECT url FROM images")
        urls.update(row[0] for row in cur.fetchall())

        # Load blocked URLs (deleted images we don't want to re-download)
        cur = self.conn.execute("SELECT url FROM blocked_urls")
        urls.update(row[0] for row in cur.fetchall())

        return urls

    def _start_background_loop(self):
        """Start the dedicated asyncio loop in a background thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _ensure_loop_running(self):
        """Make sure the background loop is running, restart if needed."""
        if self.loop is None or not self.loop.is_running():
            logger.info("[ImageManager] Restarting background loop...")
            # Start a fresh loop
            self.loop = None
            self.thread = threading.Thread(target=self._start_background_loop, daemon=True)
            self.thread.start()
            # Wait for loop to be ready
            import time
            for _ in range(50):  # Max 5 seconds
                if self.loop and self.loop.is_running():
                    break
                time.sleep(0.1)
            logger.info("[ImageManager] Background loop restarted")

    def schedule(self, coro):
        """Schedule a coroutine on the dedicated background asyncio loop."""
        if self._shutting_down:
            logger.info("[ImageManager] Ignoring task - shutdown in progress")
            return None

        # Auto-recover if loop is dead
        self._ensure_loop_running()

        if self.loop is None or not self.loop.is_running():
            logger.error("[ERROR] ImageManager background loop failed to start")
            return None

        try:
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        except RuntimeError as e:
            if "shutdown" in str(e).lower() or "closed" in str(e).lower():
                logger.warning("[ImageManager] Loop was closed, restarting...")
                self._shutting_down = False  # Reset shutdown flag
                self._ensure_loop_running()
                return asyncio.run_coroutine_threadsafe(coro, self.loop)
            raise

    def shutdown(self):
        """Aggressively stop all downloads and shutdown the background loop."""
        self._shutting_down = True
        logger.info("[ImageManager] Shutdown requested - cancelling all tasks...")

        if self.loop and self.loop.is_running():
            # Cancel all pending tasks
            def cancel_all():
                try:
                    tasks = asyncio.all_tasks(self.loop)
                    for task in tasks:
                        task.cancel()
                except Exception as e:
                    logger.debug(f"[ImageManager] Task cancellation: {e}")
                self.loop.stop()

            self.loop.call_soon_threadsafe(cancel_all)

            # Wait briefly for loop to stop
            import time
            for _ in range(10):  # Max 1 second
                if not self.loop.is_running():
                    break
                time.sleep(0.1)

        logger.info("[ImageManager] Shutdown complete")

    def is_url_saved(self, url: str) -> bool:
        """Quick in-memory check if URL is already saved."""
        return url in self.existing_urls

    def add_image(self, metadata: dict):
        """Insert image metadata into DB, ignoring duplicates."""
        columns = [
            'id', 'filename', 'path', 'thumb_path', 'url', 'source', 'query',
            'width', 'height', 'alt', 'tags', 'preview_only'
        ]
        placeholders = ", ".join(["?"] * len(columns))
        column_names = ", ".join(columns)

        values = tuple(
            metadata.get(col, '') if col not in ('preview_only',) else metadata.get(col, 0)
            for col in columns
        )

        try:
            with self.conn:
                self.conn.execute(f"""
                    INSERT OR IGNORE INTO images ({column_names})
                    VALUES ({placeholders})
                """, values)

            url = metadata['url']
            if url not in self.existing_urls:
                self.existing_urls.add(url)

        except sqlite3.IntegrityError:
            pass
        except Exception as e:
            logger.error(f"[DB INSERT ERROR] {e}")

    @staticmethod
    def generate_filename(tags: list, width: int, height: int, ext: str = ".jpg") -> str:
        safe_tags = "_".join([t.lower().replace(" ", "_")[:15] for t in tags[:3] if t.strip()])
        if not safe_tags:
            safe_tags = "image"
        unique_id = uuid.uuid4().hex[:8]
        return f"{safe_tags}_{width}x{height}_{unique_id}{ext}"

    async def create_thumbnail(self, session: aiohttp.ClientSession, url: str) -> dict | None:
        """Fetch just enough data to make thumbnail + get size. No full save."""
        if self._shutting_down:
            return None

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None

                data = io.BytesIO()
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    if self._shutting_down:
                        return None
                    data.write(chunk)
                    if data.tell() > 3 * 1024 * 1024:
                        break

                data.seek(0)

                # Suppress truncated image warnings
                original_filters = warnings.filters.copy()
                original_showwarning = warnings.showwarning

                def noop_showwarning(*args, **kwargs):
                    pass

                warnings.showwarning = noop_showwarning
                warnings.filters = []

                try:
                    img = Image.open(data)
                    img.load()
                    width, height = img.size
                finally:
                    warnings.showwarning = original_showwarning
                    warnings.filters = original_filters

                img = img.convert("RGB")
                img.thumbnail((300, 300))

                thumb_filename = f"thumb_{uuid.uuid4().hex[:12]}.jpg"
                thumb_path = THUMBS_DIR / thumb_filename
                img.save(thumb_path, "JPEG", quality=85, optimize=True)

                return {
                    "thumb_path": f"images/thumbs/{thumb_filename}",
                    "width": width,
                    "height": height
                }

        except asyncio.CancelledError:
            return None
        except Exception as e:
            if "truncated" not in str(e).lower():
                logger.error(f"[THUMBNAIL ERROR] {url}: {e}")
            return None

    async def download_and_save(self, session: aiohttp.ClientSession, url: str, tags: list,
                                source: str, query: str, alt: str = "", preview_only: bool = False) -> dict | None:
        if self._shutting_down:
            return None

        # Thread-safe duplicate check
        if url in self.existing_urls:
            return None

        try:
            with self.conn:
                cur = self.conn.cursor()
                cur.execute("SELECT 1 FROM images WHERE url = ?", (url,))
                if cur.fetchone():
                    self.existing_urls.add(url)
                    return None
        except sqlite3.Error:
            pass

        try:
            thumb_info = await self.create_thumbnail(session, url)
            if not thumb_info:
                return None

            original_path = None
            if not preview_only:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()

                content_type = resp.headers.get("Content-Type", "")
                ext = ".jpg" if "jpeg" in content_type.lower() else ".png"
                filename = self.generate_filename(tags, thumb_info["width"], thumb_info["height"], ext)
                filepath = ORIGINALS_DIR / filename
                filepath.write_bytes(data)
                original_path = f"images/originals/{filename}"

            metadata = {
                "id": str(uuid.uuid4()),
                "filename": os.path.basename(original_path or thumb_info["thumb_path"]),
                "path": original_path or "",
                "thumb_path": thumb_info["thumb_path"],
                "url": url,
                "source": source,
                "query": query,
                "width": thumb_info["width"],
                "height": thumb_info["height"],
                "alt": alt,
                "tags": json.dumps(tags),
                "preview_only": 1 if preview_only else 0
            }

            # Direct DB insert (thread-safe with connection)
            try:
                with self.conn:
                    self.conn.execute("""
                        INSERT OR IGNORE INTO images
                        (id, filename, path, thumb_path, url, source, query, width, height, alt, tags, preview_only)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        metadata['id'],
                        metadata['filename'],
                        metadata['path'],
                        metadata['thumb_path'],
                        metadata['url'],
                        metadata['source'],
                        metadata['query'],
                        metadata['width'],
                        metadata['height'],
                        metadata['alt'],
                        metadata['tags'],
                        metadata['preview_only']
                    ))
                self.existing_urls.add(url)
            except sqlite3.IntegrityError:
                pass

            return metadata

        except asyncio.CancelledError:
            return None
        except Exception as e:
            logger.error(f"[SAVE ERROR] {url}: {e}")
            return None

    async def search_pixabay(self, session: aiohttp.ClientSession, query: str, page: int = 1, per_page: int = 200):
        if not PIXABAY_KEY:
            return []
        url = "https://pixabay.com/api/"
        params = {
            "key": PIXABAY_KEY,
            "q": query,
            "per_page": per_page,
            "page": page,
            "image_type": "photo",
            "safesearch": "true"
        }
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                results = []
                for hit in data.get("hits", []):
                    img_url = hit["largeImageURL"]
                    if self.is_url_saved(img_url):
                        continue
                    tags = [t.strip() for t in hit["tags"].split(",") if t.strip()]
                    alt = ""
                    results.append({
                        "url": img_url,
                        "tags": tags,
                        "source": "Pixabay",
                        "query": query,
                        "alt": alt
                    })
                return results
        except Exception as e:
            logger.error(f"[PIXABAY ERROR] {e}")
            return []

    async def search_pexels(self, session: aiohttp.ClientSession, query: str, page: int = 1, per_page: int = 80):
        if not PEXELS_KEY:
            return []
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_KEY}
        params = {"query": query, "per_page": per_page, "page": page}
        try:
            async with session.get(url, params=params, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                results = []
                for photo in data.get("photos", []):
                    img_url = photo["src"]["large2x"]
                    if self.is_url_saved(img_url):
                        continue
                    alt = photo.get("alt", "")
                    tags = [query.strip()]
                    results.append({
                        "url": img_url,
                        "tags": tags,
                        "source": "Pexels",
                        "query": query,
                        "alt": alt
                    })
                return results
        except Exception as e:
            logger.error(f"[PEXELS ERROR] {e}")
            return []

    async def search_unsplash(self, session: aiohttp.ClientSession, query: str, page: int = 1, per_page: int = 30):
        if not UNSPLASH_KEY:
            return []
        search_url = "https://api.unsplash.com/search/photos"
        headers = {"Authorization": f"Client-ID {UNSPLASH_KEY}"}
        params = {"query": query, "per_page": per_page, "page": page}
        try:
            async with session.get(search_url, params=params, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

                fetch_tasks = []
                for photo in data.get("results", []):
                    photo_id = photo.get("id")
                    if photo_id:
                        full_url = f"https://api.unsplash.com/photos/{photo_id}"
                        fetch_tasks.append(session.get(full_url, headers=headers, timeout=15))

                full_responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)

                results = []
                try:
                    for search_photo, full_resp in zip(data.get("results", []), full_responses):
                        if isinstance(full_resp, Exception):
                            continue
                        if not isinstance(full_resp, aiohttp.ClientResponse):
                            continue
                        if full_resp.status != 200:
                            full_resp.close()
                            continue

                        try:
                            full_data = await full_resp.json()
                        finally:
                            full_resp.close()

                        img_url = search_photo["urls"]["full"]
                        if self.is_url_saved(img_url):
                            continue

                        tags = [tag.get("title", "") for tag in full_data.get("tags", []) if tag.get("title")]
                        alt = full_data.get("alt_description", "") or full_data.get("description", "") or ""

                        results.append({
                            "url": img_url,
                            "tags": tags,
                            "source": "Unsplash",
                            "query": query,
                            "alt": alt
                        })
                finally:
                    # Ensure all responses are closed even if loop exits early
                    for resp in full_responses:
                        if isinstance(resp, aiohttp.ClientResponse) and not resp.closed:
                            resp.close()

                return results
        except Exception as e:
            logger.error(f"[UNSPLASH ERROR] {e}")
            return []

    async def search_all(self, query: str, sources: dict) -> list:
        """
        sources = {
            "pixabay": 2,    # fetch 2 pages from Pixabay
            "pexels": 3,     # fetch 3 pages from Pexels
            "unsplash": 1    # fetch 1 page from Unsplash
        }
        """
        async with aiohttp.ClientSession() as session:
            tasks = []

            if (pages := sources.get("pixabay", 0)) > 0:
                for page in range(1, pages + 1):
                    tasks.append(self.search_pixabay(session, query, page=page))

            if (pages := sources.get("pexels", 0)) > 0:
                for page in range(1, pages + 1):
                    tasks.append(self.search_pexels(session, query, page=page))

            if (pages := sources.get("unsplash", 0)) > 0:
                for page in range(1, pages + 1):
                    tasks.append(self.search_unsplash(session, query, page=page))

            all_results = await asyncio.gather(*tasks, return_exceptions=True)
            combined = []
            for result_list in all_results:
                if isinstance(result_list, list):
                    combined.extend(result_list)
            return combined

    def get_all_images(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM images ORDER BY downloaded_at DESC")
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in rows]

    def delete_images(self, image_ids: list) -> tuple[int, int]:
        """Delete images from database and filesystem."""
        if not image_ids:
            return (0, 0)

        deleted = 0
        failed = 0

        for img_id in image_ids:
            try:
                cur = self.conn.cursor()
                cur.execute("SELECT url, path, thumb_path FROM images WHERE id = ?", (img_id,))
                row = cur.fetchone()

                if not row:
                    failed += 1
                    continue

                url, original_path, thumb_path = row

                if original_path:
                    full_path = PROJECT_ROOT / original_path
                    if full_path.exists():
                        try:
                            full_path.unlink()
                        except Exception as e:
                            logger.error(f"[DELETE FILE ERROR] {full_path}: {e}")

                if thumb_path:
                    full_thumb = PROJECT_ROOT / thumb_path
                    if full_thumb.exists():
                        try:
                            full_thumb.unlink()
                        except Exception as e:
                            logger.error(f"[DELETE THUMB ERROR] {full_thumb}: {e}")

                cur.execute("SELECT source FROM images WHERE id = ?", (img_id,))
                source_row = cur.fetchone()
                source = source_row[0] if source_row else ""

                with self.conn:
                    self.conn.execute("DELETE FROM images WHERE id = ?", (img_id,))
                    if url:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO blocked_urls (url, source) VALUES (?, ?)",
                            (url, source)
                        )

                deleted += 1

            except Exception as e:
                logger.error(f"[DELETE ERROR] Image {img_id}: {e}")
                failed += 1

        return (deleted, failed)

    def close(self):
        if self.conn:
            self.conn.close()

    def get_semaphore(self, max_concurrent: int = 60):
        """High-performance setting for fast batch downloads."""
        return asyncio.Semaphore(max_concurrent)
