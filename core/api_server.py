# core/api_server.py
# Flask REST API server for ImageBuddy

import threading
import queue
import time
import uuid
import json
import os
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, request, send_file, Response
from werkzeug.serving import make_server

from core import logger
from core.image_manager import ImageManager, THUMBS_DIR, ORIGINALS_DIR


class APIServer:
    """Thread-safe Flask API server for ImageBuddy."""

    def __init__(self, image_manager: ImageManager, vision_registry, host='127.0.0.1', port=5000):
        self.image_manager = image_manager
        self.vision_registry = vision_registry
        self.host = host
        self.port = port

        self.app = Flask(__name__)
        self.app.config['JSON_SORT_KEYS'] = False

        self.server = None
        self.server_thread = None
        self.running = False
        self.start_time = None

        # Task tracking for async operations
        self.tasks = {}
        self.task_lock = threading.Lock()

        # Background worker for async tasks
        self.task_queue = queue.Queue()
        self.worker_thread = None
        self.worker_running = False

        # Vision lock for thread-safe access
        self.vision_lock = threading.Lock()

        self._register_routes()

    def _register_routes(self):
        """Register all API endpoints."""

        # ========== STATUS & STATS ==========

        @self.app.route('/api/v1/status')
        def status():
            """Health check endpoint."""
            uptime = time.time() - self.start_time if self.start_time else 0
            return jsonify({
                'success': True,
                'data': {
                    'status': 'running',
                    'version': '1.0.0',
                    'uptime_seconds': round(uptime, 2),
                    'uptime_formatted': self._format_uptime(uptime)
                }
            })

        @self.app.route('/api/v1/stats')
        def stats():
            """Get image statistics."""
            try:
                images = self.image_manager.get_all_images()

                # Count by source
                by_source = {}
                by_query = {}
                total_size = 0

                for img in images:
                    source = img.get('source', 'Unknown')
                    by_source[source] = by_source.get(source, 0) + 1

                    query = img.get('query', 'Unknown')
                    by_query[query] = by_query.get(query, 0) + 1

                # Disk usage
                originals_size = sum(f.stat().st_size for f in ORIGINALS_DIR.glob('*') if f.is_file())
                thumbs_size = sum(f.stat().st_size for f in THUMBS_DIR.glob('*') if f.is_file())

                return jsonify({
                    'success': True,
                    'data': {
                        'total_images': len(images),
                        'by_source': by_source,
                        'by_query': dict(sorted(by_query.items(), key=lambda x: x[1], reverse=True)[:20]),
                        'vision_processed': sum(1 for img in images if img.get('vision_processed')),
                        'disk_usage': {
                            'originals_mb': round(originals_size / 1024 / 1024, 2),
                            'thumbs_mb': round(thumbs_size / 1024 / 1024, 2),
                            'total_mb': round((originals_size + thumbs_size) / 1024 / 1024, 2)
                        }
                    }
                })
            except Exception as e:
                logger.error(f"[API] Stats error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # ========== IMAGES CRUD ==========

        @self.app.route('/api/v1/images')
        def get_images():
            """Get all images with optional filtering and pagination."""
            try:
                page = request.args.get('page', 1, type=int)
                per_page = request.args.get('per_page', 50, type=int)
                source = request.args.get('source', '')
                query_filter = request.args.get('query', '')
                vision_processed = request.args.get('vision_processed', '')

                per_page = min(per_page, 500)  # Cap at 500

                images = self.image_manager.get_all_images()

                # Apply filters
                if source:
                    images = [img for img in images if img.get('source', '').lower() == source.lower()]
                if query_filter:
                    images = [img for img in images if query_filter.lower() in img.get('query', '').lower()]
                if vision_processed:
                    vp = vision_processed.lower() == 'true'
                    images = [img for img in images if bool(img.get('vision_processed')) == vp]

                # Pagination
                total = len(images)
                total_pages = (total + per_page - 1) // per_page
                start = (page - 1) * per_page
                end = start + per_page
                paginated = images[start:end]

                return jsonify({
                    'success': True,
                    'data': {
                        'images': paginated,
                        'total': total,
                        'page': page,
                        'per_page': per_page,
                        'total_pages': total_pages
                    }
                })
            except Exception as e:
                logger.error(f"[API] Get images error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/images/<image_id>')
        def get_image(image_id):
            """Get single image by ID."""
            try:
                images = self.image_manager.get_all_images()
                image = next((img for img in images if img.get('id') == image_id), None)

                if not image:
                    return jsonify({'success': False, 'error': 'Image not found'}), 404

                return jsonify({'success': True, 'data': image})
            except Exception as e:
                logger.error(f"[API] Get image error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/images/<image_id>', methods=['DELETE'])
        def delete_image(image_id):
            """Delete single image."""
            try:
                deleted, failed = self.image_manager.delete_images([image_id])

                if deleted > 0:
                    return jsonify({'success': True, 'data': {'deleted': deleted}})
                else:
                    return jsonify({'success': False, 'error': 'Image not found or delete failed'}), 404
            except Exception as e:
                logger.error(f"[API] Delete image error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/images/delete', methods=['POST'])
        def delete_images_batch():
            """Batch delete images."""
            try:
                data = request.get_json() or {}
                ids = data.get('ids', [])

                if not ids:
                    return jsonify({'success': False, 'error': 'No image IDs provided'}), 400

                deleted, failed = self.image_manager.delete_images(ids)

                return jsonify({
                    'success': True,
                    'data': {'deleted': deleted, 'failed': failed}
                })
            except Exception as e:
                logger.error(f"[API] Batch delete error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/images/<image_id>', methods=['PUT'])
        def update_image(image_id):
            """Update image metadata (tags, alt)."""
            try:
                data = request.get_json() or {}

                updates = []
                values = []

                if 'tags' in data:
                    tags = data['tags'] if isinstance(data['tags'], list) else []
                    updates.append('tags = ?')
                    values.append(json.dumps(tags))

                if 'alt' in data:
                    updates.append('alt = ?')
                    values.append(data['alt'])

                if not updates:
                    return jsonify({'success': False, 'error': 'No updates provided'}), 400

                values.append(image_id)
                sql = f"UPDATE images SET {', '.join(updates)} WHERE id = ?"

                with self.image_manager.conn:
                    cursor = self.image_manager.conn.execute(sql, values)
                    if cursor.rowcount == 0:
                        return jsonify({'success': False, 'error': 'Image not found'}), 404

                # Return updated image
                images = self.image_manager.get_all_images()
                image = next((img for img in images if img.get('id') == image_id), None)

                return jsonify({'success': True, 'data': image})
            except Exception as e:
                logger.error(f"[API] Update image error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/images/<image_id>/file')
        def get_image_file(image_id):
            """Serve original image file."""
            try:
                images = self.image_manager.get_all_images()
                image = next((img for img in images if img.get('id') == image_id), None)

                if not image:
                    return jsonify({'success': False, 'error': 'Image not found'}), 404

                path = image.get('path', '')
                if path:
                    full_path = Path(path)
                    if not full_path.is_absolute():
                        full_path = Path(__file__).parent.parent / path

                    if full_path.exists():
                        return send_file(full_path, mimetype='image/jpeg')

                # Fall back to thumbnail
                return get_image_thumb(image_id)
            except Exception as e:
                logger.error(f"[API] Get image file error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/images/<image_id>/thumb')
        def get_image_thumb(image_id):
            """Serve thumbnail."""
            try:
                images = self.image_manager.get_all_images()
                image = next((img for img in images if img.get('id') == image_id), None)

                if not image:
                    return jsonify({'success': False, 'error': 'Image not found'}), 404

                thumb_path = image.get('thumb_path', '')
                if thumb_path:
                    full_path = Path(thumb_path)
                    if not full_path.is_absolute():
                        full_path = Path(__file__).parent.parent / thumb_path

                    if full_path.exists():
                        return send_file(full_path, mimetype='image/jpeg')

                return jsonify({'success': False, 'error': 'Thumbnail not found'}), 404
            except Exception as e:
                logger.error(f"[API] Get thumb error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/images/query', methods=['POST'])
        def query_images():
            """Advanced image query with multiple filters."""
            try:
                data = request.get_json() or {}
                filters = data.get('filters', {})
                sort = data.get('sort', {'field': 'downloaded_at', 'order': 'desc'})
                pagination = data.get('pagination', {'page': 1, 'per_page': 50})

                images = self.image_manager.get_all_images()

                # Apply filters
                if filters.get('source'):
                    sources = filters['source'] if isinstance(filters['source'], list) else [filters['source']]
                    sources_lower = [s.lower() for s in sources]
                    images = [img for img in images if img.get('source', '').lower() in sources_lower]

                if filters.get('query'):
                    q = filters['query'].lower()
                    images = [img for img in images if q in img.get('query', '').lower()]

                if filters.get('tags_contain'):
                    tags_filter = filters['tags_contain']
                    if isinstance(tags_filter, str):
                        tags_filter = [tags_filter]
                    def has_tags(img):
                        try:
                            img_tags = json.loads(img.get('tags', '[]'))
                            img_tags_lower = [t.lower() for t in img_tags]
                            return any(t.lower() in img_tags_lower for t in tags_filter)
                        except:
                            return False
                    images = [img for img in images if has_tags(img)]

                if filters.get('width_min'):
                    images = [img for img in images if (img.get('width') or 0) >= filters['width_min']]
                if filters.get('width_max'):
                    images = [img for img in images if (img.get('width') or 0) <= filters['width_max']]
                if filters.get('height_min'):
                    images = [img for img in images if (img.get('height') or 0) >= filters['height_min']]
                if filters.get('height_max'):
                    images = [img for img in images if (img.get('height') or 0) <= filters['height_max']]

                if 'vision_processed' in filters:
                    vp = filters['vision_processed']
                    images = [img for img in images if bool(img.get('vision_processed')) == vp]

                if 'preview_only' in filters:
                    po = filters['preview_only']
                    images = [img for img in images if bool(img.get('preview_only')) == po]

                # Sorting
                sort_field = sort.get('field', 'downloaded_at')
                sort_order = sort.get('order', 'desc')
                reverse = sort_order.lower() == 'desc'
                images.sort(key=lambda x: x.get(sort_field, ''), reverse=reverse)

                # Pagination
                page = pagination.get('page', 1)
                per_page = min(pagination.get('per_page', 50), 500)
                total = len(images)
                total_pages = (total + per_page - 1) // per_page
                start = (page - 1) * per_page
                paginated = images[start:start + per_page]

                return jsonify({
                    'success': True,
                    'data': {
                        'images': paginated,
                        'total': total,
                        'page': page,
                        'per_page': per_page,
                        'total_pages': total_pages
                    }
                })
            except Exception as e:
                logger.error(f"[API] Query images error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # ========== SEARCH ==========

        @self.app.route('/api/v1/search/pixabay')
        def search_pixabay():
            """Search Pixabay."""
            return self._handle_search('pixabay')

        @self.app.route('/api/v1/search/pexels')
        def search_pexels():
            """Search Pexels."""
            return self._handle_search('pexels')

        @self.app.route('/api/v1/search/unsplash')
        def search_unsplash():
            """Search Unsplash."""
            return self._handle_search('unsplash')

        @self.app.route('/api/v1/search', methods=['POST'])
        def search_all():
            """Search all sources."""
            try:
                data = request.get_json() or {}
                query = data.get('query', '')
                sources = data.get('sources', {'pixabay': 1, 'pexels': 1, 'unsplash': 1})

                if not query:
                    return jsonify({'success': False, 'error': 'Query required'}), 400

                # Run search
                import asyncio
                import aiohttp

                async def do_search():
                    return await self.image_manager.search_all(query, sources)

                future = self.image_manager.schedule(do_search())
                if future:
                    results = future.result(timeout=60)
                    return jsonify({
                        'success': True,
                        'data': {
                            'results': results,
                            'count': len(results),
                            'query': query
                        }
                    })
                else:
                    return jsonify({'success': False, 'error': 'Search failed to schedule'}), 500

            except Exception as e:
                logger.error(f"[API] Search all error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # ========== DOWNLOAD ==========

        @self.app.route('/api/v1/download', methods=['POST'])
        def download_single():
            """Download single image from URL."""
            try:
                data = request.get_json() or {}
                url = data.get('url', '')
                tags = data.get('tags', [])
                source = data.get('source', 'API')
                query = data.get('query', 'api-download')
                alt = data.get('alt', '')
                preview_only = data.get('preview_only', False)

                if not url:
                    return jsonify({'success': False, 'error': 'URL required'}), 400

                # Check duplicate
                if self.image_manager.is_url_saved(url):
                    return jsonify({'success': False, 'error': 'Image already exists'}), 409

                # Download
                import asyncio
                import aiohttp

                async def do_download():
                    async with aiohttp.ClientSession() as session:
                        return await self.image_manager.download_and_save(
                            session, url, tags, source, query, alt, preview_only
                        )

                future = self.image_manager.schedule(do_download())
                if future:
                    result = future.result(timeout=120)
                    if result:
                        return jsonify({'success': True, 'data': result})
                    else:
                        return jsonify({'success': False, 'error': 'Download failed'}), 500
                else:
                    return jsonify({'success': False, 'error': 'Download failed to schedule'}), 500

            except Exception as e:
                logger.error(f"[API] Download error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/download/batch', methods=['POST'])
        def download_batch():
            """Batch download images (async)."""
            try:
                data = request.get_json() or {}
                items = data.get('items', [])
                preview_only = data.get('preview_only', False)

                if not items:
                    return jsonify({'success': False, 'error': 'No items provided'}), 400

                # Create task
                task_id = self._create_task('download_batch', len(items))

                # Queue the work
                self.task_queue.put({
                    'type': 'download_batch',
                    'task_id': task_id,
                    'items': items,
                    'preview_only': preview_only
                })

                return jsonify({
                    'success': True,
                    'data': {
                        'task_id': task_id,
                        'total': len(items),
                        'message': 'Download started'
                    }
                })
            except Exception as e:
                logger.error(f"[API] Batch download error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/tasks/<task_id>')
        def get_task_status(task_id):
            """Get async task status."""
            with self.task_lock:
                task = self.tasks.get(task_id)
                if not task:
                    return jsonify({'success': False, 'error': 'Task not found'}), 404
                return jsonify({'success': True, 'data': task})

        # ========== VISION ==========

        @self.app.route('/api/v1/vision/status')
        def vision_status():
            """Get vision engine status."""
            try:
                with self.vision_lock:
                    total = self.vision_registry.get_count()
                    loaded = self.vision_registry.get_loaded_count()

                return jsonify({
                    'success': True,
                    'data': {
                        'instances_total': total,
                        'instances_loaded': loaded,
                        'ready': loaded > 0
                    }
                })
            except Exception as e:
                logger.error(f"[API] Vision status error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/vision/load', methods=['POST'])
        def vision_load():
            """Load vision instances."""
            try:
                data = request.get_json() or {}
                device = data.get('device', 'cpu')
                count = data.get('count', 1)

                from core.vision_manager import VisionManager

                loaded = 0
                for _ in range(count):
                    manager = VisionManager(root=None)

                    if device == 'auto':
                        device_spec = 0  # First GPU
                    elif device == 'cpu':
                        device_spec = 'cpu'
                    else:
                        device_spec = int(device)

                    manager.load(device_spec)

                    with self.vision_lock:
                        self.vision_registry.add(manager)
                    loaded += 1

                return jsonify({
                    'success': True,
                    'data': {
                        'loaded': loaded,
                        'total': self.vision_registry.get_count()
                    }
                })
            except Exception as e:
                logger.error(f"[API] Vision load error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/vision/unload', methods=['POST'])
        def vision_unload():
            """Unload all vision instances."""
            try:
                with self.vision_lock:
                    self.vision_registry.unload_all()

                return jsonify({
                    'success': True,
                    'data': {'message': 'All instances unloaded'}
                })
            except Exception as e:
                logger.error(f"[API] Vision unload error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/vision/analyze/<image_id>', methods=['POST'])
        def vision_analyze_single(image_id):
            """Analyze single image."""
            try:
                data = request.get_json() or {}
                need_objects = data.get('need_objects', True)
                apply_to_db = data.get('apply_to_db', True)
                auto_load = data.get('auto_load', True)  # Auto-load if no instances

                # Get image
                images = self.image_manager.get_all_images()
                image = next((img for img in images if img.get('id') == image_id), None)

                if not image:
                    return jsonify({'success': False, 'error': 'Image not found'}), 404

                # Get path
                path = image.get('path') or image.get('thumb_path')
                if not path:
                    return jsonify({'success': False, 'error': 'No image file found'}), 404

                full_path = Path(path)
                if not full_path.is_absolute():
                    full_path = Path(__file__).parent.parent / path

                if not full_path.exists():
                    return jsonify({'success': False, 'error': 'Image file not found'}), 404

                # Get a loaded instance, auto-load if needed
                with self.vision_lock:
                    instances = [m for m in self.vision_registry.instances if m.is_loaded()]

                if not instances:
                    if auto_load:
                        logger.info("[API] No vision instances loaded, auto-loading...")
                        load_result = self._auto_load_vision()
                        if not load_result['success']:
                            return jsonify({'success': False, 'error': load_result['message']}), 500
                        with self.vision_lock:
                            instances = [m for m in self.vision_registry.instances if m.is_loaded()]
                    else:
                        return jsonify({'success': False, 'error': 'No vision instances loaded'}), 400

                manager = instances[0]

                # Synchronous analysis with event
                result_event = threading.Event()
                result_data = {}

                def callback(data):
                    result_data.update(data)
                    result_event.set()

                manager.send_analysis(str(full_path), callback, need_objects, direct_callback=True)

                if result_event.wait(timeout=60):
                    if 'error' in result_data:
                        return jsonify({'success': False, 'error': result_data['error']}), 500

                    analysis = result_data.get('analysis', {})

                    # Apply to database if requested
                    if apply_to_db and analysis:
                        updates = ['vision_processed = 1']
                        values = []

                        if analysis.get('caption'):
                            updates.append('alt = ?')
                            values.append(analysis['caption'])

                        if analysis.get('objects'):
                            updates.append('tags = ?')
                            values.append(json.dumps(analysis['objects']))

                        values.append(image_id)
                        sql = f"UPDATE images SET {', '.join(updates)} WHERE id = ?"
                        with self.image_manager.conn:
                            self.image_manager.conn.execute(sql, values)

                    return jsonify({
                        'success': True,
                        'data': {
                            'image_id': image_id,
                            'analysis': analysis,
                            'applied_to_db': apply_to_db
                        }
                    })
                else:
                    return jsonify({'success': False, 'error': 'Analysis timeout'}), 504

            except Exception as e:
                logger.error(f"[API] Vision analyze error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/vision/analyze', methods=['POST'])
        def vision_analyze_batch():
            """Batch analyze images (async)."""
            try:
                data = request.get_json() or {}
                image_ids = data.get('ids', [])
                need_objects = data.get('need_objects', True)
                auto_load = data.get('auto_load', True)  # Auto-load if no instances

                if not image_ids:
                    return jsonify({'success': False, 'error': 'No image IDs provided'}), 400

                # Check vision instances, auto-load if needed
                with self.vision_lock:
                    loaded = self.vision_registry.get_loaded_count()

                if loaded == 0:
                    if auto_load:
                        logger.info("[API] No vision instances loaded, auto-loading for batch...")
                        load_result = self._auto_load_vision()
                        if not load_result['success']:
                            return jsonify({'success': False, 'error': load_result['message']}), 500
                    else:
                        return jsonify({'success': False, 'error': 'No vision instances loaded'}), 400

                # Create task
                task_id = self._create_task('vision_analyze', len(image_ids))

                # Queue the work
                self.task_queue.put({
                    'type': 'vision_analyze',
                    'task_id': task_id,
                    'image_ids': image_ids,
                    'need_objects': need_objects
                })

                return jsonify({
                    'success': True,
                    'data': {
                        'task_id': task_id,
                        'total': len(image_ids),
                        'message': 'Analysis started'
                    }
                })
            except Exception as e:
                logger.error(f"[API] Batch analyze error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # ========== COMBO ENDPOINTS ==========

        @self.app.route('/api/v1/combo/search-download', methods=['POST'])
        def combo_search_download():
            """Search and download results."""
            try:
                data = request.get_json() or {}
                query = data.get('query', '')
                sources = data.get('sources', {'pixabay': 1})
                limit = data.get('limit', 10)
                preview_only = data.get('preview_only', False)

                if not query:
                    return jsonify({'success': False, 'error': 'Query required'}), 400

                # Create task
                task_id = self._create_task('search_download', limit)

                # Queue the work
                self.task_queue.put({
                    'type': 'search_download',
                    'task_id': task_id,
                    'query': query,
                    'sources': sources,
                    'limit': limit,
                    'preview_only': preview_only
                })

                return jsonify({
                    'success': True,
                    'data': {
                        'task_id': task_id,
                        'message': 'Search and download started'
                    }
                })
            except Exception as e:
                logger.error(f"[API] Combo search-download error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/combo/download-analyze', methods=['POST'])
        def combo_download_analyze():
            """Download and analyze single image."""
            try:
                data = request.get_json() or {}
                url = data.get('url', '')
                tags = data.get('tags', [])
                source = data.get('source', 'API')
                query = data.get('query', 'api-download')
                alt = data.get('alt', '')
                auto_load = data.get('auto_load', True)  # Auto-load if no instances

                if not url:
                    return jsonify({'success': False, 'error': 'URL required'}), 400

                # Check vision, auto-load if needed
                with self.vision_lock:
                    loaded = self.vision_registry.get_loaded_count()

                if loaded == 0:
                    if auto_load:
                        logger.info("[API] No vision instances loaded, auto-loading for download-analyze...")
                        load_result = self._auto_load_vision()
                        if not load_result['success']:
                            return jsonify({'success': False, 'error': load_result['message']}), 500
                    else:
                        return jsonify({'success': False, 'error': 'No vision instances loaded'}), 400

                # Download first
                import aiohttp

                async def do_download():
                    async with aiohttp.ClientSession() as session:
                        return await self.image_manager.download_and_save(
                            session, url, tags, source, query, alt, False
                        )

                future = self.image_manager.schedule(do_download())
                if not future:
                    return jsonify({'success': False, 'error': 'Download failed'}), 500

                result = future.result(timeout=120)
                if not result:
                    return jsonify({'success': False, 'error': 'Download failed'}), 500

                image_id = result.get('id')
                path = result.get('path') or result.get('thumb_path')

                if not path:
                    return jsonify({
                        'success': True,
                        'data': {
                            'image': result,
                            'analysis': None,
                            'message': 'Downloaded but no file for analysis'
                        }
                    })

                full_path = Path(path)
                if not full_path.is_absolute():
                    full_path = Path(__file__).parent.parent / path

                # Analyze
                with self.vision_lock:
                    instances = [m for m in self.vision_registry.instances if m.is_loaded()]

                if not instances:
                    return jsonify({
                        'success': True,
                        'data': {
                            'image': result,
                            'analysis': None,
                            'message': 'Downloaded but no vision instance available'
                        }
                    })

                manager = instances[0]
                result_event = threading.Event()
                analysis_data = {}

                def callback(data):
                    analysis_data.update(data)
                    result_event.set()

                manager.send_analysis(str(full_path), callback, True, direct_callback=True)

                if result_event.wait(timeout=60):
                    analysis = analysis_data.get('analysis', {})

                    # Apply to DB
                    if analysis:
                        updates = ['vision_processed = 1']
                        values = []
                        if analysis.get('caption'):
                            updates.append('alt = ?')
                            values.append(analysis['caption'])
                        if analysis.get('objects'):
                            updates.append('tags = ?')
                            values.append(json.dumps(analysis['objects']))
                        values.append(image_id)
                        sql = f"UPDATE images SET {', '.join(updates)} WHERE id = ?"
                        with self.image_manager.conn:
                            self.image_manager.conn.execute(sql, values)

                    # Get updated image
                    images = self.image_manager.get_all_images()
                    updated_image = next((img for img in images if img.get('id') == image_id), result)

                    return jsonify({
                        'success': True,
                        'data': {
                            'image': updated_image,
                            'analysis': analysis
                        }
                    })
                else:
                    return jsonify({
                        'success': True,
                        'data': {
                            'image': result,
                            'analysis': None,
                            'message': 'Downloaded but analysis timed out'
                        }
                    })

            except Exception as e:
                logger.error(f"[API] Combo download-analyze error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/combo/analyze-unprocessed', methods=['POST'])
        def combo_analyze_unprocessed():
            """Analyze all unprocessed images."""
            try:
                data = request.get_json() or {}
                limit = data.get('limit', 100)
                sources = data.get('sources', [])  # Empty = all sources
                auto_load = data.get('auto_load', True)  # Auto-load if no instances

                # Check vision, auto-load if needed
                with self.vision_lock:
                    loaded = self.vision_registry.get_loaded_count()

                if loaded == 0:
                    if auto_load:
                        logger.info("[API] No vision instances loaded, auto-loading for analyze-unprocessed...")
                        load_result = self._auto_load_vision()
                        if not load_result['success']:
                            return jsonify({'success': False, 'error': load_result['message']}), 500
                    else:
                        return jsonify({'success': False, 'error': 'No vision instances loaded'}), 400

                # Get unprocessed images
                images = self.image_manager.get_all_images()
                unprocessed = [img for img in images if not img.get('vision_processed')]

                if sources:
                    sources_lower = [s.lower() for s in sources]
                    unprocessed = [img for img in unprocessed if img.get('source', '').lower() in sources_lower]

                unprocessed = unprocessed[:limit]

                if not unprocessed:
                    return jsonify({
                        'success': True,
                        'data': {
                            'message': 'No unprocessed images found',
                            'count': 0
                        }
                    })

                image_ids = [img['id'] for img in unprocessed]

                # Create task
                task_id = self._create_task('vision_analyze', len(image_ids))

                # Queue the work
                self.task_queue.put({
                    'type': 'vision_analyze',
                    'task_id': task_id,
                    'image_ids': image_ids,
                    'need_objects': True
                })

                return jsonify({
                    'success': True,
                    'data': {
                        'task_id': task_id,
                        'total': len(image_ids),
                        'message': 'Analysis started'
                    }
                })
            except Exception as e:
                logger.error(f"[API] Combo analyze-unprocessed error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/combo/smart-analyze', methods=['POST'])
        def combo_smart_analyze():
            """Smart analyze: auto-load vision, analyze images, auto-unload.

            This is a comprehensive endpoint that handles the full workflow:
            1. Auto-loads vision instances using smart GPU detection (if not loaded)
            2. Analyzes specified images (or all unprocessed)
            3. Auto-unloads instances after completion (if requested)

            Request body:
            {
                "ids": [],              # Image IDs to analyze (empty = all unprocessed)
                "sources": [],          # Filter by sources (empty = all)
                "limit": 100,           # Max images to process
                "apply_captions": true, # Apply captions to DB
                "apply_tags": true,     # Apply tags to DB
                "auto_unload": true,    # Unload instances after completion
                "reprocess_short_captions": false,  # Re-analyze images with short captions
                "reprocess_few_tags": false         # Re-analyze images with few tags
            }
            """
            try:
                data = request.get_json() or {}
                image_ids = data.get('ids', [])
                sources = data.get('sources', [])
                limit = data.get('limit', 100)
                apply_captions = data.get('apply_captions', True)
                apply_tags = data.get('apply_tags', True)
                auto_unload = data.get('auto_unload', True)
                reprocess_short = data.get('reprocess_short_captions', False)
                reprocess_few_tags = data.get('reprocess_few_tags', False)

                # Get images to process
                all_images = self.image_manager.get_all_images()

                if image_ids:
                    # Use specified IDs
                    images_to_process = [img for img in all_images if img['id'] in image_ids]
                else:
                    # Find unprocessed or matching reprocess criteria
                    images_to_process = []
                    for img in all_images:
                        should_process = False

                        if not img.get('vision_processed'):
                            should_process = True
                        elif reprocess_short:
                            caption = img.get('alt') or ''
                            if len(caption) < 50:
                                should_process = True
                        elif reprocess_few_tags:
                            try:
                                tags = json.loads(img.get('tags') or '[]')
                                if len(tags) <= 1:
                                    should_process = True
                            except:
                                should_process = True

                        if should_process:
                            # Apply source filter
                            if sources:
                                sources_lower = [s.lower() for s in sources]
                                if img.get('source', '').lower() in sources_lower:
                                    images_to_process.append(img)
                            else:
                                images_to_process.append(img)

                images_to_process = images_to_process[:limit]

                if not images_to_process:
                    return jsonify({
                        'success': True,
                        'data': {
                            'message': 'No images to analyze',
                            'processed': 0,
                            'total': 0
                        }
                    })

                # Check/load vision instances
                with self.vision_lock:
                    loaded_count = self.vision_registry.get_loaded_count()

                load_info = None
                if loaded_count == 0:
                    logger.info("[API] Smart analyze: auto-loading vision...")
                    load_result = self._auto_load_vision()
                    if not load_result['success']:
                        return jsonify({'success': False, 'error': load_result['message']}), 500
                    load_info = load_result

                # Create task for async processing
                task_id = self._create_task('smart_analyze', len(images_to_process))

                # Queue the work
                self.task_queue.put({
                    'type': 'smart_analyze',
                    'task_id': task_id,
                    'images': images_to_process,
                    'apply_captions': apply_captions,
                    'apply_tags': apply_tags,
                    'auto_unload': auto_unload
                })

                response_data = {
                    'task_id': task_id,
                    'total': len(images_to_process),
                    'message': 'Smart analysis started'
                }

                if load_info:
                    response_data['vision_loaded'] = load_info

                return jsonify({'success': True, 'data': response_data})

            except Exception as e:
                logger.error(f"[API] Smart analyze error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/v1/combo/search-download-analyze', methods=['POST'])
        def combo_search_download_analyze():
            """Full pipeline: search, download, and analyze images.

            This is the most comprehensive endpoint:
            1. Searches specified sources
            2. Downloads results
            3. Auto-loads vision if needed
            4. Analyzes all downloaded images
            5. Auto-unloads vision after completion

            Request body:
            {
                "query": "nature",
                "sources": {"pixabay": 1, "pexels": 1},
                "limit": 10,
                "preview_only": false,
                "auto_unload": true
            }
            """
            try:
                data = request.get_json() or {}
                query = data.get('query', '')
                sources = data.get('sources', {'pixabay': 1})
                limit = data.get('limit', 10)
                preview_only = data.get('preview_only', False)
                auto_unload = data.get('auto_unload', True)

                if not query:
                    return jsonify({'success': False, 'error': 'Query required'}), 400

                # Create task
                task_id = self._create_task('search_download_analyze', limit)

                # Queue the work
                self.task_queue.put({
                    'type': 'search_download_analyze',
                    'task_id': task_id,
                    'query': query,
                    'sources': sources,
                    'limit': limit,
                    'preview_only': preview_only,
                    'auto_unload': auto_unload
                })

                return jsonify({
                    'success': True,
                    'data': {
                        'task_id': task_id,
                        'message': 'Search-download-analyze pipeline started',
                        'query': query
                    }
                })
            except Exception as e:
                logger.error(f"[API] Search-download-analyze error: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

    def _handle_search(self, source: str):
        """Handle single-source search."""
        try:
            query = request.args.get('query', '')
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', type=int)

            if not query:
                return jsonify({'success': False, 'error': 'Query required'}), 400

            import aiohttp

            async def do_search():
                async with aiohttp.ClientSession() as session:
                    if source == 'pixabay':
                        return await self.image_manager.search_pixabay(session, query, page, per_page or 200)
                    elif source == 'pexels':
                        return await self.image_manager.search_pexels(session, query, page, per_page or 80)
                    elif source == 'unsplash':
                        return await self.image_manager.search_unsplash(session, query, page, per_page or 30)
                    return []

            future = self.image_manager.schedule(do_search())
            if future:
                results = future.result(timeout=30)
                return jsonify({
                    'success': True,
                    'data': {
                        'results': results,
                        'count': len(results),
                        'source': source,
                        'query': query,
                        'page': page
                    }
                })
            else:
                return jsonify({'success': False, 'error': 'Search failed'}), 500

        except Exception as e:
            logger.error(f"[API] Search {source} error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    def _create_task(self, task_type: str, total: int) -> str:
        """Create a new tracked task."""
        task_id = str(uuid.uuid4())
        with self.task_lock:
            self.tasks[task_id] = {
                'id': task_id,
                'type': task_type,
                'status': 'running',
                'total': total,
                'completed': 0,
                'errors': [],
                'created_at': time.time(),
                'result': None
            }
        return task_id

    def _update_task(self, task_id: str, **kwargs):
        """Update task status."""
        with self.task_lock:
            if task_id in self.tasks:
                self.tasks[task_id].update(kwargs)

    def _format_uptime(self, seconds: float) -> str:
        """Format uptime as HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _load_vision_settings(self) -> dict:
        """Load vision settings from config file."""
        from core import system_monitor

        defaults = {
            "vision_auto_load": True,
            "vision_auto_unload": False,
            "vision_gpu_strategy": "auto",
            "vision_gpu_enabled": {},
            "vision_gpu_instances": {},
            "vision_allow_cpu": None,
            "vision_cpu_instances": 1,
            "vision_max_per_gpu": 4,
            "vision_max_total": 8,
            "vision_reserved_vram": 0.5,
        }

        try:
            settings_file = Path(__file__).parent.parent / "config" / "settings.json"
            if settings_file.exists():
                with open(settings_file, "r") as f:
                    saved = json.load(f)
                    for key in defaults:
                        if key in saved:
                            defaults[key] = saved[key]
        except Exception as e:
            logger.error(f"[API] Failed to load vision settings: {e}")

        # If allow_cpu not explicitly set, default based on GPU availability
        if defaults["vision_allow_cpu"] is None:
            gpu_count = system_monitor.get_gpu_count()
            defaults["vision_allow_cpu"] = (gpu_count == 0)

        return defaults

    def _auto_load_vision(self, device='auto') -> dict:
        """Auto-load vision instances using smart GPU detection (same as UI).

        Args:
            device: Override device selection. Options:
                - 'auto': Use settings-based smart detection (default)
                - 'cpu': Force CPU only
                - 'gpu': Use best available GPU
                - int: Specific GPU index

        Returns:
            dict with 'success', 'loaded', 'is_cpu', 'message'
        """
        from core import system_monitor
        from core.vision_manager import VisionManager

        try:
            settings = self._load_vision_settings()
            strategy = settings["vision_gpu_strategy"]
            max_per_gpu = settings["vision_max_per_gpu"]
            max_total = settings["vision_max_total"]
            reserved_vram = settings["vision_reserved_vram"]
            allow_cpu = settings["vision_allow_cpu"]
            cpu_instances = settings["vision_cpu_instances"]
            gpu_enabled = settings["vision_gpu_enabled"]
            gpu_instances = settings["vision_gpu_instances"]

            # Override strategy if device specified
            if device == 'cpu':
                strategy = 'cpu_only'
            elif device == 'gpu':
                strategy = 'single_best'
            elif isinstance(device, int):
                strategy = 'specific'
                gpu_enabled = {str(device): True}
                gpu_instances = {str(device): max_per_gpu}

            gpu_count = system_monitor.get_gpu_count()
            load_plan = []
            is_cpu_only = False

            if strategy == "cpu_only":
                is_cpu_only = True
                load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))
                logger.info(f"[API] CPU-only mode: {cpu_instances} instance(s)")

            elif strategy == "specific":
                for i in range(gpu_count):
                    if gpu_enabled.get(str(i), True):
                        stats = system_monitor.get_gpu_stats(i)
                        if stats:
                            count = min(gpu_instances.get(str(i), 2), max_per_gpu)
                            load_plan.append((i, count, stats["name"]))
                            logger.info(f"[API] GPU {i} ({stats['name']}): {count} instance(s)")

                if not load_plan and allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))

            elif strategy == "all_gpus":
                for i in range(gpu_count):
                    stats = system_monitor.get_gpu_stats(i)
                    if stats:
                        available_vram = stats["vram_total_gb"] - stats["vram_used_gb"]
                        if available_vram >= 2.5:
                            usable_vram = available_vram - reserved_vram
                            count = max(1, min(max_per_gpu, int(usable_vram / 2.0)))
                            load_plan.append((i, count, stats["name"]))
                            logger.info(f"[API] GPU {i} ({stats['name']}): {count} instance(s), {available_vram:.1f}GB free")

                if not load_plan and allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))

            elif strategy == "single_best":
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
                    logger.info(f"[API] Best GPU {best_gpu_idx} ({best_name}): {count} instance(s), {best_vram:.1f}GB free")
                elif allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))

            else:  # "auto" - smart detection (default)
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
                    usable_gpus.sort(key=lambda x: x[3], reverse=True)
                    for gpu_idx, count, name, vram in usable_gpus:
                        load_plan.append((gpu_idx, count, name))
                        logger.info(f"[API] GPU {gpu_idx} ({name}): {count} instance(s), {vram:.1f}GB free")
                elif allow_cpu:
                    is_cpu_only = True
                    load_plan.append(("cpu", min(cpu_instances, max_total), "CPU"))
                    logger.info("[API] No suitable GPUs, using CPU")

            # Enforce max_total limit
            total_instances = sum(p[1] for p in load_plan)
            if total_instances > max_total:
                scale = max_total / total_instances
                load_plan = [(dev, max(1, int(cnt * scale)), name) for dev, cnt, name in load_plan]
                total_instances = sum(p[1] for p in load_plan)

            if not load_plan:
                return {
                    'success': False,
                    'loaded': 0,
                    'is_cpu': False,
                    'message': 'No GPU or CPU available for loading'
                }

            # Load instances according to plan
            loaded = 0
            load_events = []

            for device_spec, count, name in load_plan:
                for _ in range(count):
                    manager = VisionManager(root=None)
                    event = threading.Event()

                    def on_loaded(e=event):
                        e.set()

                    manager.on_loaded_callback = on_loaded
                    manager.load(device_spec)

                    with self.vision_lock:
                        self.vision_registry.add(manager)

                    load_events.append(event)

            # Wait for all instances to load (with timeout)
            for event in load_events:
                if event.wait(timeout=60):
                    loaded += 1

            if loaded > 0:
                if is_cpu_only:
                    msg = f"Loaded {loaded} CPU instance(s)"
                elif len(load_plan) == 1:
                    _, _, name = load_plan[0]
                    msg = f"Loaded {loaded} instance(s) on {name}"
                else:
                    msg = f"Loaded {loaded} instance(s) across {len(load_plan)} device(s)"

                return {
                    'success': True,
                    'loaded': loaded,
                    'is_cpu': is_cpu_only,
                    'message': msg
                }
            else:
                return {
                    'success': False,
                    'loaded': 0,
                    'is_cpu': False,
                    'message': 'Failed to load any vision instances'
                }

        except Exception as e:
            logger.error(f"[API] Failed to auto-load vision: {e}")
            return {
                'success': False,
                'loaded': 0,
                'is_cpu': False,
                'message': str(e)
            }

    def _unload_all_vision(self):
        """Unload all vision instances and free memory."""
        try:
            with self.vision_lock:
                self.vision_registry.unload_all()
            logger.info("[API] All vision instances unloaded")
            return True
        except Exception as e:
            logger.error(f"[API] Failed to unload vision: {e}")
            return False

    def _task_worker(self):
        """Process async tasks from the queue."""
        import aiohttp

        while self.worker_running:
            try:
                task = self.task_queue.get(timeout=1.0)
                if task is None:
                    break
                self._process_task(task)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[API] Task worker error: {e}")

    def _process_task(self, task: dict):
        """Process a single async task."""
        task_type = task.get('type')
        task_id = task.get('task_id')

        try:
            if task_type == 'download_batch':
                self._process_download_batch(task)
            elif task_type == 'vision_analyze':
                self._process_vision_analyze(task)
            elif task_type == 'search_download':
                self._process_search_download(task)
            elif task_type == 'smart_analyze':
                self._process_smart_analyze(task)
            elif task_type == 'search_download_analyze':
                self._process_search_download_analyze(task)
            else:
                logger.error(f"[API] Unknown task type: {task_type}")
                self._update_task(task_id, status='failed', error='Unknown task type')
        except Exception as e:
            logger.error(f"[API] Task processing error: {e}")
            self._update_task(task_id, status='failed', error=str(e))

    def _process_download_batch(self, task: dict):
        """Process batch download task."""
        import aiohttp

        task_id = task['task_id']
        items = task['items']
        preview_only = task.get('preview_only', False)

        async def do_downloads():
            completed = 0
            errors = []

            async with aiohttp.ClientSession() as session:
                for item in items:
                    try:
                        url = item.get('url', '')
                        if not url:
                            continue

                        result = await self.image_manager.download_and_save(
                            session,
                            url,
                            item.get('tags', []),
                            item.get('source', 'API'),
                            item.get('query', 'batch'),
                            item.get('alt', ''),
                            preview_only
                        )

                        if result:
                            completed += 1
                        else:
                            errors.append(f"Failed: {url}")

                        self._update_task(task_id, completed=completed, errors=errors)

                    except Exception as e:
                        errors.append(f"{url}: {str(e)}")

            return completed, errors

        future = self.image_manager.schedule(do_downloads())
        if future:
            completed, errors = future.result(timeout=600)
            self._update_task(task_id, status='completed', completed=completed, errors=errors)
        else:
            self._update_task(task_id, status='failed', error='Failed to schedule downloads')

    def _process_vision_analyze(self, task: dict):
        """Process batch vision analysis task."""
        task_id = task['task_id']
        image_ids = task['image_ids']
        need_objects = task.get('need_objects', True)

        completed = 0
        errors = []

        with self.vision_lock:
            instances = [m for m in self.vision_registry.instances if m.is_loaded()]

        if not instances:
            self._update_task(task_id, status='failed', error='No vision instances')
            return

        images = self.image_manager.get_all_images()
        images_map = {img['id']: img for img in images}

        for idx, image_id in enumerate(image_ids):
            try:
                image = images_map.get(image_id)
                if not image:
                    errors.append(f"Image not found: {image_id}")
                    continue

                path = image.get('path') or image.get('thumb_path')
                if not path:
                    errors.append(f"No file: {image_id}")
                    continue

                full_path = Path(path)
                if not full_path.is_absolute():
                    full_path = Path(__file__).parent.parent / path

                if not full_path.exists():
                    errors.append(f"File missing: {image_id}")
                    continue

                # Round-robin instance selection
                manager = instances[idx % len(instances)]

                result_event = threading.Event()
                analysis_data = {}

                def callback(data):
                    analysis_data.update(data)
                    result_event.set()

                manager.send_analysis(str(full_path), callback, need_objects, direct_callback=True)

                if result_event.wait(timeout=60):
                    if 'error' in analysis_data:
                        errors.append(f"{image_id}: {analysis_data['error']}")
                    else:
                        analysis = analysis_data.get('analysis', {})

                        # Apply to DB
                        if analysis:
                            updates = ['vision_processed = 1']
                            values = []
                            if analysis.get('caption'):
                                updates.append('alt = ?')
                                values.append(analysis['caption'])
                            if analysis.get('objects'):
                                updates.append('tags = ?')
                                values.append(json.dumps(analysis['objects']))
                            values.append(image_id)
                            sql = f"UPDATE images SET {', '.join(updates)} WHERE id = ?"
                            with self.image_manager.conn:
                                self.image_manager.conn.execute(sql, values)

                        completed += 1
                else:
                    errors.append(f"Timeout: {image_id}")

                self._update_task(task_id, completed=completed, errors=errors)

            except Exception as e:
                errors.append(f"{image_id}: {str(e)}")

        self._update_task(task_id, status='completed', completed=completed, errors=errors)

    def _process_search_download(self, task: dict):
        """Process search and download task."""
        import aiohttp

        task_id = task['task_id']
        query = task['query']
        sources = task['sources']
        limit = task['limit']
        preview_only = task.get('preview_only', False)

        async def do_search_download():
            # Search first
            results = await self.image_manager.search_all(query, sources)
            results = results[:limit]

            self._update_task(task_id, total=len(results))

            completed = 0
            errors = []

            async with aiohttp.ClientSession() as session:
                for item in results:
                    try:
                        result = await self.image_manager.download_and_save(
                            session,
                            item['url'],
                            item.get('tags', []),
                            item.get('source', 'Search'),
                            query,
                            item.get('alt', ''),
                            preview_only
                        )

                        if result:
                            completed += 1

                        self._update_task(task_id, completed=completed)

                    except Exception as e:
                        errors.append(str(e))

            return completed, errors

        future = self.image_manager.schedule(do_search_download())
        if future:
            completed, errors = future.result(timeout=600)
            self._update_task(task_id, status='completed', completed=completed, errors=errors)
        else:
            self._update_task(task_id, status='failed', error='Failed to schedule')

    def _process_smart_analyze(self, task: dict):
        """Process smart analyze task: analyze images with auto-unload."""
        task_id = task['task_id']
        images = task['images']
        apply_captions = task.get('apply_captions', True)
        apply_tags = task.get('apply_tags', True)
        auto_unload = task.get('auto_unload', True)

        completed = 0
        errors = []
        project_root = Path(__file__).parent.parent

        with self.vision_lock:
            instances = [m for m in self.vision_registry.instances if m.is_loaded()]

        if not instances:
            self._update_task(task_id, status='failed', error='No vision instances available')
            return

        # Check if CPU mode (for throttling)
        is_cpu = all(getattr(m, 'device', 'cpu') == 'cpu' for m in instances)

        for idx, img in enumerate(images):
            try:
                path = img.get('path') or img.get('thumb_path')
                if not path:
                    errors.append(f"No file for {img['id']}")
                    continue

                full_path = Path(path)
                if not full_path.is_absolute():
                    full_path = project_root / path

                if not full_path.exists():
                    errors.append(f"File missing: {img['id']}")
                    continue

                # Round-robin instance selection
                manager = instances[idx % len(instances)]

                result_event = threading.Event()
                analysis_data = {}

                def callback(data):
                    analysis_data.update(data)
                    result_event.set()

                manager.send_analysis(str(full_path), callback, apply_tags, direct_callback=True)

                if result_event.wait(timeout=60):
                    if 'error' in analysis_data:
                        errors.append(f"{img['id']}: {analysis_data['error']}")
                    else:
                        analysis = analysis_data.get('analysis', {})

                        if analysis:
                            updates = ['vision_processed = 1']
                            values = []

                            if apply_captions and analysis.get('caption'):
                                updates.append('alt = ?')
                                values.append(analysis['caption'])

                            if apply_tags and analysis.get('objects'):
                                # Merge with existing tags
                                cur = self.image_manager.conn.execute(
                                    "SELECT tags FROM images WHERE id = ?", (img['id'],)
                                )
                                row = cur.fetchone()
                                existing = []
                                if row and row[0]:
                                    try:
                                        existing = [t.lower() for t in json.loads(row[0])]
                                    except:
                                        pass
                                new_tags = analysis['objects']
                                merged = new_tags + [t for t in existing if t.lower() not in [n.lower() for n in new_tags]]
                                updates.append('tags = ?')
                                values.append(json.dumps(merged))

                            values.append(img['id'])
                            sql = f"UPDATE images SET {', '.join(updates)} WHERE id = ?"
                            with self.image_manager.conn:
                                self.image_manager.conn.execute(sql, values)

                        completed += 1
                else:
                    errors.append(f"Timeout: {img['id']}")

                self._update_task(task_id, completed=completed, errors=errors)

                # CPU throttle
                if is_cpu and (idx + 1) % 3 == 0:
                    time.sleep(0.5)

            except Exception as e:
                errors.append(f"{img['id']}: {str(e)}")

        # Auto-unload if requested
        if auto_unload:
            logger.info("[API] Smart analyze: auto-unloading vision instances")
            self._unload_all_vision()

        self._update_task(task_id, status='completed', completed=completed, errors=errors,
                          result={'auto_unloaded': auto_unload})

    def _process_search_download_analyze(self, task: dict):
        """Process full pipeline: search, download, analyze, unload."""
        import aiohttp

        task_id = task['task_id']
        query = task['query']
        sources = task['sources']
        limit = task['limit']
        preview_only = task.get('preview_only', False)
        auto_unload = task.get('auto_unload', True)

        # Phase 1: Search and download
        async def do_search_download():
            results = await self.image_manager.search_all(query, sources)
            results = results[:limit]

            self._update_task(task_id, total=len(results), result={'phase': 'downloading'})

            downloaded = []
            errors = []

            async with aiohttp.ClientSession() as session:
                for item in results:
                    try:
                        result = await self.image_manager.download_and_save(
                            session,
                            item['url'],
                            item.get('tags', []),
                            item.get('source', 'Search'),
                            query,
                            item.get('alt', ''),
                            preview_only
                        )

                        if result:
                            downloaded.append(result)

                        self._update_task(task_id, completed=len(downloaded))

                    except Exception as e:
                        errors.append(str(e))

            return downloaded, errors

        future = self.image_manager.schedule(do_search_download())
        if not future:
            self._update_task(task_id, status='failed', error='Failed to schedule downloads')
            return

        downloaded, download_errors = future.result(timeout=600)

        if not downloaded:
            self._update_task(task_id, status='completed', completed=0,
                              errors=download_errors, result={'downloaded': 0, 'analyzed': 0})
            return

        # Phase 2: Auto-load vision if needed
        self._update_task(task_id, result={'phase': 'loading_vision'})

        with self.vision_lock:
            loaded = self.vision_registry.get_loaded_count()

        if loaded == 0:
            load_result = self._auto_load_vision()
            if not load_result['success']:
                self._update_task(task_id, status='completed',
                                  result={'downloaded': len(downloaded), 'analyzed': 0,
                                          'error': 'Vision load failed: ' + load_result['message']})
                return

        # Phase 3: Analyze downloaded images
        self._update_task(task_id, result={'phase': 'analyzing'})

        with self.vision_lock:
            instances = [m for m in self.vision_registry.instances if m.is_loaded()]

        if not instances:
            self._update_task(task_id, status='completed',
                              result={'downloaded': len(downloaded), 'analyzed': 0,
                                      'error': 'No vision instances available'})
            return

        project_root = Path(__file__).parent.parent
        analyzed = 0
        analyze_errors = []

        for idx, img in enumerate(downloaded):
            try:
                path = img.get('path') or img.get('thumb_path')
                if not path:
                    continue

                full_path = Path(path)
                if not full_path.is_absolute():
                    full_path = project_root / path

                if not full_path.exists():
                    continue

                manager = instances[idx % len(instances)]

                result_event = threading.Event()
                analysis_data = {}

                def callback(data):
                    analysis_data.update(data)
                    result_event.set()

                manager.send_analysis(str(full_path), callback, True, direct_callback=True)

                if result_event.wait(timeout=60):
                    if 'analysis' in analysis_data:
                        analysis = analysis_data['analysis']

                        updates = ['vision_processed = 1']
                        values = []

                        if analysis.get('caption'):
                            updates.append('alt = ?')
                            values.append(analysis['caption'])

                        if analysis.get('objects'):
                            updates.append('tags = ?')
                            values.append(json.dumps(analysis['objects']))

                        values.append(img['id'])
                        sql = f"UPDATE images SET {', '.join(updates)} WHERE id = ?"
                        with self.image_manager.conn:
                            self.image_manager.conn.execute(sql, values)

                        analyzed += 1

            except Exception as e:
                analyze_errors.append(str(e))

        # Phase 4: Auto-unload if requested
        if auto_unload:
            logger.info("[API] Search-download-analyze: auto-unloading vision")
            self._unload_all_vision()

        self._update_task(task_id, status='completed', completed=len(downloaded),
                          errors=download_errors + analyze_errors,
                          result={'downloaded': len(downloaded), 'analyzed': analyzed,
                                  'auto_unloaded': auto_unload})

    def start(self) -> bool:
        """Start the API server in a background thread."""
        if self.running:
            logger.warning("[API] Server already running")
            return False

        try:
            self.start_time = time.time()
            self.server = make_server(self.host, self.port, self.app, threaded=True)

            # Start server thread
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name="APIServer"
            )
            self.server_thread.start()

            # Start background worker
            self.worker_running = True
            self.worker_thread = threading.Thread(
                target=self._task_worker,
                daemon=True,
                name="APITaskWorker"
            )
            self.worker_thread.start()

            self.running = True
            logger.info(f"[API] Server started on http://{self.host}:{self.port}")
            return True

        except Exception as e:
            logger.error(f"[API] Failed to start server: {e}")
            return False

    def stop(self):
        """Gracefully stop the API server."""
        if not self.running:
            return

        logger.info("[API] Stopping server...")
        self.running = False
        self.worker_running = False

        # Signal worker to stop
        self.task_queue.put(None)

        # Shutdown server
        if self.server:
            self.server.shutdown()

        logger.info("[API] Server stopped")

    def _run_server(self):
        """Run the Flask server."""
        try:
            self.server.serve_forever()
        except Exception as e:
            logger.error(f"[API] Server error: {e}")
            self.running = False

    def is_running(self) -> bool:
        """Check if server is running."""
        return self.running

    def get_url(self) -> str:
        """Get the server URL."""
        return f"http://{self.host}:{self.port}/api/v1"
