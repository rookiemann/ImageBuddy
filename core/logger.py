# core/logger.py
# Logging system for ImageBuddy with in-memory buffer for UI

import logging
import sys
from datetime import datetime
from pathlib import Path
from collections import deque

# Log files in project root
LOG_DIR = Path(__file__).parent.parent
DEBUG_LOG = LOG_DIR / "debug_log.txt"
ERROR_LOG = LOG_DIR / "error_log.txt"
INFO_LOG = LOG_DIR / "info_log.txt"

# In-memory buffer for UI (last N entries)
_log_buffer = deque(maxlen=1000)


class SimpleFormatter(logging.Formatter):
    """Formatter that adds timestamp."""

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        return f"[{timestamp}] {record.getMessage()}"


class ConsoleFormatter(logging.Formatter):
    """Colored console formatter."""

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'
    }

    def format(self, record):
        if sys.stdout.isatty():
            color = self.COLORS.get(record.levelname, '')
            reset = self.COLORS['RESET']
            return f"{color}{record.getMessage()}{reset}"
        return record.getMessage()


class BufferHandler(logging.Handler):
    """Handler that stores logs in memory buffer for UI display."""

    def emit(self, record):
        try:
            entry = {
                'timestamp': datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S'),
                'level': record.levelname,
                'message': record.getMessage(),
            }
            _log_buffer.append(entry)
        except Exception:
            self.handleError(record)


def setup_logging():
    """Initialize the logging system."""

    logger = logging.getLogger("imagedownloader")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(ConsoleFormatter())
    logger.addHandler(console)

    # Buffer handler for UI
    buffer_handler = BufferHandler()
    buffer_handler.setLevel(logging.DEBUG)
    logger.addHandler(buffer_handler)

    # Debug log file
    try:
        debug_handler = logging.FileHandler(DEBUG_LOG, encoding='utf-8')
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(SimpleFormatter())
        debug_handler.addFilter(lambda r: r.levelno < logging.INFO)
        logger.addHandler(debug_handler)
    except Exception:
        pass  # Skip if file can't be created

    # Info log file
    try:
        info_handler = logging.FileHandler(INFO_LOG, encoding='utf-8')
        info_handler.setLevel(logging.INFO)
        info_handler.setFormatter(SimpleFormatter())
        info_handler.addFilter(lambda r: r.levelno < logging.ERROR)
        logger.addHandler(info_handler)
    except Exception:
        pass

    # Error log file
    try:
        error_handler = logging.FileHandler(ERROR_LOG, encoding='utf-8')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(SimpleFormatter())
        logger.addHandler(error_handler)
    except Exception:
        pass

    return logger


# Initialize on import
_logger = setup_logging()


def debug(msg: str):
    _logger.debug(msg)


def info(msg: str):
    _logger.info(msg)


def warning(msg: str):
    _logger.warning(msg)


def error(msg: str):
    _logger.error(msg)


def exception(msg: str):
    _logger.exception(msg)


def get_logger(component: str) -> logging.Logger:
    return _logger.getChild(component)


def get_log_buffer() -> list:
    """Get all logs currently in the buffer (last 1000 entries)."""
    return list(_log_buffer)


def clear_log_buffer():
    """Clear the in-memory log buffer."""
    _log_buffer.clear()
