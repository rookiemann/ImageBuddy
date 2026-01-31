# ImageBuddy

A portable Windows app for searching, downloading, and managing stock images from Pixabay, Pexels, and Unsplash. Features parallel AI-powered captioning with Florence-2 and a REST API for automation.

## Features

- **Multi-Source Search** - Search Pixabay, Pexels, and Unsplash simultaneously
- **Batch Download** - Download multiple images with automatic tagging
- **Image Management** - Browse, filter, and organize your downloaded images
- **Parallel AI Captioning** - Generate descriptions using Florence-2 with multi-GPU support
- **REST API** - Control everything programmatically for automation and integrations
- **GPU Accelerated** - Run multiple AI instances across GPUs for maximum throughput

## Installation

1. **Download the latest release** from the [Releases](../../releases) page
2. **Extract** the zip file to your desired location
3. **Download** `python-portable.zip` from the release assets
4. **Extract** `python-portable.zip` into the ImageBuddy folder
   - You should have a `python` folder inside ImageBuddy
5. **Run** `run.bat`

### First Run

On first launch, the app will:
1. Install base dependencies automatically (~50MB)
2. Prompt you to choose AI installation:
   - **GPU (NVIDIA CUDA)** - ~2.5GB download, 10-50x faster processing
   - **CPU** - ~200MB download, works on any system
   - **Skip** - Run without AI features

The Florence-2 AI model (~3GB) downloads automatically when you first use AI captioning.

## API Keys

To search and download images, you need API keys from:
- [Pixabay](https://pixabay.com/api/docs/)
- [Pexels](https://www.pexels.com/api/)
- [Unsplash](https://unsplash.com/developers)

Enter your keys in the Settings tab after launching the app.

## Requirements

- Windows 10/11
- ~500MB disk space (without AI)
- ~4GB disk space (with AI model)
- NVIDIA GPU with CUDA support (optional, for faster AI)

## Folder Structure

```
ImageBuddy/
├── python/          # Portable Python (from release asset)
├── images/          # Your downloaded images
├── models/          # AI model (downloaded on first use)
├── config/          # Settings
└── run.bat          # Launch the app
```

## API

The built-in REST API runs on `http://127.0.0.1:5000/api/v1` by default. Enable it from the API tab.

Key endpoints:
- `GET /images` - List images
- `POST /search` - Search multiple sources
- `POST /download` - Download images
- `POST /vision/analyze` - AI caption images
- `GET /status` - Health check

## License

MIT
