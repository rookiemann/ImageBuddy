# core/system_monitor.py
"""
System resource monitor for CPU, RAM, and GPU usage.
"""

import psutil
from typing import Optional
from core import logger

# GPU monitoring (nvidia-ml-py)
_nvml_available = False
_nvml_initialized = False

try:
    import pynvml
    _nvml_available = True
except ImportError:
    logger.debug("[SystemMonitor] pynvml not installed - GPU monitoring via nvidia-smi fallback")


def _init_nvml():
    """Initialize NVML if available."""
    global _nvml_initialized
    if _nvml_available and not _nvml_initialized:
        try:
            pynvml.nvmlInit()
            _nvml_initialized = True
            count = pynvml.nvmlDeviceGetCount()
            logger.info(f"[SystemMonitor] NVML initialized - {count} GPU(s) detected")
        except Exception as e:
            logger.error(f"[SystemMonitor] NVML init failed: {e}")


def _shutdown_nvml():
    """Shutdown NVML cleanly."""
    global _nvml_initialized
    if _nvml_initialized:
        try:
            pynvml.nvmlShutdown()
            _nvml_initialized = False
            logger.info("[SystemMonitor] NVML shutdown complete")
        except Exception as e:
            logger.error(f"[SystemMonitor] NVML shutdown error: {e}")


def get_cpu_percent() -> float:
    """Get current CPU usage percentage (0-100)."""
    return psutil.cpu_percent(interval=None)


def get_ram_percent() -> float:
    """Get current RAM usage percentage (0-100)."""
    return psutil.virtual_memory().percent


def get_ram_details() -> dict:
    """Get detailed RAM info."""
    mem = psutil.virtual_memory()
    return {
        "percent": mem.percent,
        "used_gb": mem.used / (1024 ** 3),
        "total_gb": mem.total / (1024 ** 3),
        "available_gb": mem.available / (1024 ** 3)
    }


def get_gpu_count() -> int:
    """Get number of NVIDIA GPUs."""
    if not _nvml_initialized:
        _init_nvml()
    if not _nvml_initialized:
        return 0
    try:
        return pynvml.nvmlDeviceGetCount()
    except:
        return 0


def get_gpu_stats(index: int = 0) -> Optional[dict]:
    """Get stats for a specific GPU."""
    if not _nvml_initialized:
        _init_nvml()
    if not _nvml_initialized:
        return None

    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode('utf-8')

        # Utilization
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)

        # Memory
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        vram_used_gb = mem.used / (1024 ** 3)
        vram_total_gb = mem.total / (1024 ** 3)
        vram_percent = (mem.used / mem.total) * 100 if mem.total > 0 else 0

        # Temperature
        try:
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        except:
            temp = None

        return {
            "name": name,
            "util": util.gpu,
            "vram_percent": vram_percent,
            "vram_used_gb": vram_used_gb,
            "vram_total_gb": vram_total_gb,
            "temp": temp
        }
    except Exception as e:
        logger.error(f"[SystemMonitor] GPU {index} query failed: {e}")
        return None


def get_all_gpu_stats() -> list:
    """Get stats for all GPUs."""
    count = get_gpu_count()
    results = []
    for i in range(count):
        stats = get_gpu_stats(i)
        if stats:
            results.append(stats)
    return results


def get_stats() -> dict:
    """Get all system stats in one call."""
    return {
        "cpu": get_cpu_percent(),
        "ram": get_ram_percent(),
        "ram_details": get_ram_details(),
        "gpus": get_all_gpu_stats()
    }


# Initialize CPU percent tracking
psutil.cpu_percent(interval=None)
