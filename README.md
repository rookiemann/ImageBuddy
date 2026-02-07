# ImageBuddy

![License: MIT](https://img.shields.io/github/license/rookiemann/ImageBuddy) ![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue) ![Python](https://img.shields.io/badge/Python-Portable-green)

A portable Windows app for searching, downloading, and managing stock images from Pixabay, Pexels, and Unsplash. Features parallel AI-powered captioning with Florence-2 and a full REST API for automation.

---

## Features

- **Multi-Source Search** -- Search Pixabay, Pexels, and Unsplash simultaneously from one interface
- **Batch Download** -- Download multiple images with automatic tagging and metadata
- **Image Management** -- Browse, filter, query, and organize your downloaded images with a dark-themed GUI
- **Parallel AI Captioning** -- Generate descriptions using Florence-2 with multi-GPU support and multiple concurrent instances
- **REST API** -- 27-endpoint API for full programmatic control -- search, download, analyze, and combine operations
- **GPU Accelerated** -- Run multiple Florence-2 instances across GPUs for maximum captioning throughput
- **Fully Portable** -- No system Python, no admin rights, no global installs. Copy the folder and it works.

---

## Quick Start

### Installation

1. **Download the latest release** from the [Releases](../../releases) page
2. **Extract** the zip file to your desired location
3. **Download** `python-portable.zip` from the release assets
4. **Extract** `python-portable.zip` into the ImageBuddy folder (creates a `python/` subfolder)
5. **Run** `run.bat`

That's it. No pip, no conda, no PATH changes.

### First Run

On first launch, the app will:
1. Install base dependencies automatically (~50MB)
2. Prompt you to choose AI installation:
   - **GPU (NVIDIA CUDA)** -- ~2.5GB download, 10-50x faster captioning
   - **CPU** -- ~200MB download, works on any machine
   - **Skip** -- Run without AI features

The Florence-2 model (~3GB) downloads automatically the first time you use AI captioning.

---

## API Keys

To search and download images, you need free API keys from one or more of these services:

| Source | Get Your Key | Free Tier |
|--------|-------------|-----------|
| [Pixabay](https://pixabay.com/api/docs/) | Sign up at pixabay.com | Unlimited |
| [Pexels](https://www.pexels.com/api/) | Sign up at pexels.com | 200 req/hr |
| [Unsplash](https://unsplash.com/developers) | Create an app at unsplash.com | 50 req/hr |

Enter your keys in the **Settings** tab after launching the app.

---

## GUI Tabs

| Tab | Purpose |
|-----|---------|
| **Images** | Search across sources, download, browse your library, run AI captioning, manage images |
| **Settings** | API keys, download preferences, AI device selection, theme settings |
| **Log** | Real-time application log with debug info and GPU/system details |
| **API** | Start/stop the REST API server, view endpoint documentation |

---

## REST API

The built-in REST API runs on `http://127.0.0.1:5000/api/v1` by default. Enable it from the **API** tab or set `api_auto_start` in settings.

### Status & Stats

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/status` | Health check with uptime |
| `GET` | `/api/v1/stats` | Image counts, disk usage, per-source and per-query breakdowns |

### Image Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/images` | List all images (supports filtering, pagination) |
| `GET` | `/api/v1/images/<id>` | Get image metadata by ID |
| `PUT` | `/api/v1/images/<id>` | Update image metadata |
| `DELETE` | `/api/v1/images/<id>` | Delete a single image |
| `POST` | `/api/v1/images/delete` | Batch delete images |
| `GET` | `/api/v1/images/<id>/file` | Download the original image file |
| `GET` | `/api/v1/images/<id>/thumb` | Get the thumbnail |
| `POST` | `/api/v1/images/query` | Advanced query with filters |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/search/pixabay` | Search Pixabay |
| `GET` | `/api/v1/search/pexels` | Search Pexels |
| `GET` | `/api/v1/search/unsplash` | Search Unsplash |
| `POST` | `/api/v1/search` | Search multiple sources at once |

### Download

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/download` | Download a single image by URL |
| `POST` | `/api/v1/download/batch` | Batch download (returns async task ID) |
| `GET` | `/api/v1/tasks/<id>` | Check async task progress |

### AI Vision (Florence-2)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/vision/status` | Check loaded model instances and GPU allocation |
| `POST` | `/api/v1/vision/load` | Load Florence-2 on a specific device |
| `POST` | `/api/v1/vision/unload` | Unload all vision instances |
| `POST` | `/api/v1/vision/analyze/<id>` | Caption a specific image |
| `POST` | `/api/v1/vision/analyze` | Caption an image by providing a file or URL |

### Combo Endpoints (Chained Operations)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/combo/search-download` | Search + download in one call |
| `POST` | `/api/v1/combo/download-analyze` | Download + AI caption |
| `POST` | `/api/v1/combo/analyze-unprocessed` | Caption all images not yet processed |
| `POST` | `/api/v1/combo/smart-analyze` | Auto-load model if needed, then caption |
| `POST` | `/api/v1/combo/search-download-analyze` | Full pipeline: search, download, and caption |

### Example: Full Pipeline via API

```bash
# Start a search-download-analyze pipeline
curl -X POST http://127.0.0.1:5000/api/v1/combo/search-download-analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "mountain landscape", "sources": ["pixabay", "pexels"], "max_results": 10}'

# Check task progress
curl http://127.0.0.1:5000/api/v1/tasks/<task_id>

# List all downloaded images with captions
curl http://127.0.0.1:5000/api/v1/images
```

---

## AI Captioning

ImageBuddy uses **Florence-2** (Microsoft) for image captioning. It runs fully locally -- no cloud API calls.

| Feature | Details |
|---------|---------|
| **Model** | Florence-2-base (~3GB download, one-time) |
| **Multi-GPU** | Load separate instances on different GPUs for parallel processing |
| **CPU fallback** | Works without a GPU (slower) |
| **Per-image** | Caption individual images or batch-process your entire library |

### Device Selection

In the GUI, each Florence-2 instance can be assigned to a specific device:
- `cuda:0`, `cuda:1`, etc. for individual GPUs
- `cpu` for CPU-only processing

Run multiple instances across GPUs to maximize throughput.

---

## Project Structure

```
ImageBuddy/
+-- run.bat                  # Launch the app
+-- app.py                   # Main entry point (Tkinter GUI)
+-- config.py                # Path resolution and settings
+-- gpu_utils.py             # GPU detection and VRAM monitoring
+-- vision_worker.py         # Florence-2 worker process
+-- requirements-base.txt    # Core dependencies
+-- requirements-gpu.txt     # NVIDIA CUDA dependencies (PyTorch)
+-- requirements-cpu.txt     # CPU-only dependencies
|
+-- core/
|   +-- api_server.py        # Flask REST API (27 endpoints)
|   +-- image_manager.py     # SQLite-backed image database
|   +-- vision_manager.py    # Florence-2 model loading and inference
|   +-- vision_registry.py   # Multi-instance GPU model management
|   +-- system_monitor.py    # CPU/GPU/RAM monitoring
|   +-- theme.py             # Dark theme configuration
|   +-- logger.py            # Application logging
|
+-- ui/
|   +-- images_tab.py        # Search, download, browse, caption UI
|   +-- settings_tab.py      # API keys, preferences, device selection
|   +-- log_tab.py           # Real-time log viewer
|   +-- api_tab.py           # API server controls
|   +-- system_footer.py     # Status bar with system metrics
|   +-- ui_utils.py          # Shared UI components
|
+-- config/
|   +-- settings.json        # User settings (API keys, preferences)
|   +-- theme.json           # Theme colors and fonts
|
+-- assets/                  # App icons
+-- python/                  # Portable Python (from release)
+-- images/                  # Downloaded images (originals + thumbnails)
+-- models/                  # Florence-2 model (auto-downloaded)
```

---

## Requirements

- **Windows 10/11** (64-bit)
- **~500MB** disk space (without AI)
- **~4GB** disk space (with Florence-2 model)
- **NVIDIA GPU with CUDA** (optional, for faster AI captioning)
- **No admin rights needed**
- **No pre-installed Python needed**

---

## Credits

- **[@rookiemann](https://github.com/rookiemann)** -- Creator and maintainer
- **[Florence-2](https://huggingface.co/microsoft/Florence-2-base)** (Microsoft) -- AI vision model
- **[Pixabay](https://pixabay.com/)**, **[Pexels](https://www.pexels.com/)**, **[Unsplash](https://unsplash.com/)** -- Image sources
- **[Claude Code](https://claude.ai/claude-code)** (Anthropic) -- AI pair programmer

---

## License

MIT License. See [LICENSE](LICENSE).
